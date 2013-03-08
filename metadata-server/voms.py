# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright 2013 Spanish National Research Council
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# mostly taken from https://github.com/IFCA/keystone-voms

import commands
import ctypes
import json
import os

import M2Crypto

SSL_CLIENT_S_DN_ENV = "SSL_CLIENT_S_DN"
SSL_CLIENT_CERT_ENV = "SSL_CLIENT_CERT"
SSL_CLIENT_CERT_CHAIN_0_ENV = "SSL_CLIENT_CERT_CHAIN_0"

# XXX Hardcoded config, to be removed from here
#CONF_VOMSPOLICY = "/etc/keystone/voms.json"
CONF_VOMSPOLICY = "voms.json"
CONF_VOMSDIR_PATH = "/etc/grid-security/vomsdir/"
CONF_VOMSCA_PATH = "/etc/grid-security/certificates/"
CONF_VOMSAPI_LIB = "libvomsapi.so.0"

# TODO enolfc
# proper error handling!

class _voms(ctypes.Structure):
    _fields_ = [
        ("siglen", ctypes.c_int32),
        ("signature", ctypes.c_char_p),
        ("user", ctypes.c_char_p),
        ("userca", ctypes.c_char_p),
        ("server", ctypes.c_char_p),
        ("serverca", ctypes.c_char_p),
        ("voname", ctypes.c_char_p),
        ("uri", ctypes.c_char_p),
        ("date1", ctypes.c_char_p),
        ("date2", ctypes.c_char_p),
        ("type", ctypes.c_int32),
        ("std", ctypes.c_void_p),
        ("custom", ctypes.c_char_p),
        ("datalen", ctypes.c_int32),
        ("version", ctypes.c_int32),
        ("fqan", ctypes.POINTER(ctypes.c_char_p)),
        ("serial", ctypes.c_char_p),
        ("ac", ctypes.c_void_p),
        ("holder", ctypes.c_void_p),
    ]

class _vomsdata(ctypes.Structure):
    _fields_ = [
        ("cdir", ctypes.c_char_p),
        ("vdir", ctypes.c_char_p),
        ("data", ctypes.POINTER(ctypes.POINTER(_voms))),
        ("workvo", ctypes.c_char_p),
        ("extra_data", ctypes.c_char_p),
        ("volen", ctypes.c_int32),
        ("extralen", ctypes.c_int32),
        ("real", ctypes.c_void_p),
    ]


class VOMS(object):
    """Context Manager for VOMS handling"""

    def __init__(self, vomsdir_path, ca_path, vomsapi_lib):
        self.VOMSApi = ctypes.CDLL(vomsapi_lib)
        self.VOMSApi.VOMS_Init.restype = ctypes.POINTER(_vomsdata)

        self.VOMSDIR = vomsdir_path
        self.CADIR = ca_path

        self.vd = None

    def __enter__(self):
        self.vd = self.VOMSApi.VOMS_Init(self.VOMSDIR, self.CADIR).contents
        return self

    def set_no_verify(self):
        """Skip verification of AC.

        This method skips the AC signature verification, this it should
        only be used for debugging and tests.
        """
        error = ctypes.c_int32(0)
        self.VOMSApi.VOMS_SetVerificationType(0x040,
                                              ctypes.byref(self.vd),
                                              ctypes.byref(error))

    def retrieve(self, cert, chain):
        """Retrieve VOMS credentials from a certificate and chain."""
        self.error = ctypes.c_int32(0)

        cert_ptr = ctypes.cast(long(cert._ptr()), ctypes.c_void_p)
        chain_ptr = ctypes.cast(long(chain._ptr()), ctypes.c_void_p)

        res = self.VOMSApi.VOMS_Retrieve(cert_ptr,
                                         chain_ptr,
                                         0,
                                         ctypes.byref(self.vd),
                                         ctypes.byref(self.error))
        if res == 0:
            return None
        else:
            return self.vd.data.contents.contents

    def __exit__(self, type, value, tb):
        self.VOMSApi.VOMS_Destroy(ctypes.byref(self.vd))


class VomsAuthNMiddleware():
    def __init__(self, app):
        self.app = app
        try:
            self.voms_json = json.loads(open(CONF_VOMSPOLICY).read())
        except ValueError:
            raise Exception("Bad formatted json data at %s" 
                                            % CONF_VOMSPOLICY)
        except:
            raise Exception("Could not load json file %s" 
                                            % CONF_VOMSPOLICY)
        self._no_verify = False

    @staticmethod
    def _get_cert_chain(ssl_info):
        """Return certificate and chain from the ssl info in M2Crypto format"""
        cert = ssl_info.get(SSL_CLIENT_CERT_ENV, "")
        chain = ssl_info.get(SSL_CLIENT_CERT_CHAIN_0_ENV, "")
        cert = M2Crypto.X509.load_cert_string(cert)
        aux = M2Crypto.X509.load_cert_string(chain)
        chain = M2Crypto.X509.X509_Stack()
        chain.push(aux)
        return cert, chain

    @staticmethod
    def _split_fqan(fqan):
        """
        gets a fqan and returns a tuple containing
        (vo/groups, role, capability)
        """
        l = fqan.split("/")
        capability = l.pop().split("=")[-1]
        role = l.pop().split("=")[-1]
        vogroup = "/".join(l)
        return (vogroup, role, capability)

    def _get_voms_info(self, ssl_info):
        """Extract voms info from ssl_info and return dict with it."""

        try:
            cert, chain = self._get_cert_chain(ssl_info)
        except M2Crypto.X509.X509Error:
            raise Exception(
                attribute="SSL data",
                target=CONTEXT_ENV)

        with VOMS(CONF_VOMSDIR_PATH, CONF_VOMSCA_PATH, CONF_VOMSAPI_LIB) as v:
            if self._no_verify:
                v.set_no_verify()
            voms_data = v.retrieve(cert, chain)
            if not voms_data:
                # TODO(enolfc): exception handling? 
                raise Exception(v.error.value)

            d = {}
            for attr in ('user', 'userca', 'server', 'serverca',
                         'voname',  'uri', 'version', 'serial',
                         ('not_before', 'date1'), ('not_after', 'date2')):
                if isinstance(attr, basestring):
                    d[attr] = getattr(voms_data, attr)
                else:
                    d[attr[0]] = getattr(voms_data, attr[1])

            d["fqans"] = []
            for fqan in iter(voms_data.fqan):
                if fqan is None:
                    break
                d["fqans"].append(fqan)

        return d

    def _get_user(self, voms_info):
        return voms_info["user"]

    def __call__(self, environ, start_response):
        #if environ.get('REMOTE_USER', None) is not None:
            # authenticated upstream
        #    return self.app(environ, start_response)

        ssl_dict = {}
        for i in (SSL_CLIENT_S_DN_ENV,
                  SSL_CLIENT_CERT_ENV,
                  SSL_CLIENT_CERT_CHAIN_0_ENV):
            ssl_dict[i] = environ.get(i, None)

        try:
            voms_info = self._get_voms_info(ssl_dict)
        except Exception, e:
            raise e # 404

        if voms_info["voname"] not in self.voms_json:
            raise Exception("Not authorized!") # 404
        environ['REMOTE_USER'] = voms_info["user"]
        environ['VONAME'] = voms_info["voname"]

        return self.app(environ, start_response)

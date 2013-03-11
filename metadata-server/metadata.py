#
# First attempt to create a meta-data server for the VMs
# TODO:
#  -> Security? Can anyone see the meta-data of any image?
#               Can anyone POST new meta-data of images?
#  -> Do we impose any kind of format to the data to be stored?
#  -> Is the OCCI uuid unique enough?
#  -> Search uuids?
#  -> When does data expire?
#

from datetime import datetime

from flask import Flask
from flask import request
from flask import jsonify

from werkzeug.exceptions import default_exceptions, HTTPException
from flask import make_response, abort as flask_abort, request
from flask.exceptions import JSONHTTPException

# abort with proper content types
# taken from http://flask.pocoo.org/snippets/97/
def abort(status_code, body=None, headers={}):
    if 'text/html' in request.headers.get("Accept", ""):
        error_cls = HTTPException
    else:
        error_cls = JSONHTTPException

    class_name = error_cls.__name__
    bases = [error_cls]
    attributes = {'code': status_code}

    if status_code in default_exceptions:
        # Mixin the Werkzeug exception
        bases.insert(0, default_exceptions[status_code])

    error_cls = type(class_name, tuple(bases), attributes)
    flask_abort(make_response(error_cls(body), status_code, headers))

# mongodb stuff
from mongokit import Connection

# configuration
DEBUG=True
MONGODB_HOST = 'localhost'
MONGODB_PORT = 27017

# create the little application object
app = Flask(__name__)
app.config.from_object(__name__)

# connect to the database
connection = Connection(app.config['MONGODB_HOST'],
                        app.config['MONGODB_PORT'])

app = Flask(__name__)

import voms
#app.wsgi_app = voms.VomsAuthNMiddleware(app.wsgi_app)

# POST image meta-data into the server
@app.route('/data', methods=['POST'])
@voms.require_voms
def put_data():
    assert(request.json)
    if 'uuid' not in request.json:
        abort(400)
    d = request.json
    if get_vm_data(d['uuid']):
        abort(400)
    d['date'] = datetime.now().isoformat()
    collection = connection['test'].vms
    collection.insert(d)
    return jsonify(uuid=d['uuid'])

def get_vm_data(uuid):
    collection = connection['test'].vms
    vm = collection.find_one({'uuid': uuid})
    if not vm:
        return None
    del vm["_id"]
    return vm

@app.route('/data/<uuid>')
def show_data(uuid):
    d = get_vm_data(uuid)
    if not d:
        abort(404)
    return jsonify(d)

@app.route('/data/<uuid>/<field>')
def get_data_field(uuid, field):
    d = get_vm_data(uuid)
    if not d:
        abort(404)
    try:
        return '%s' % d[field]
    except KeyError:
        abort(404)

if __name__ == "__main__":
    app.run(debug=True)

#!/bin/bash
#
# contextualization script
#

#set -x

# Some variables
# Location of the OS metadata
OS_METADATA_URL=http://169.254.169.254/openstack/latest/meta_data.json

# Location of the ONE metadata
ONE_CONTEXT_DEVICE=/dev/sr0
ONE_CONTEXT_SCRIPT=context.sh

# Location of our metadata server
# Could this be taken from somewhere else (context)?
METADATA_URL=http://cloud.ibergrid.eu:5001/data

# Extra curl arguments
# XXX our server does not have a proper cert  
EXTRA_CURL_ARGS="-k"

# Location of the contextualizer
CONTEXTUALIZER_PATH=/usr/local/src/context

# Try first with OpenStack meta-data
OS_META_DATA=`mktemp`
curl --retry 3 --retry-delay 0 --silent --fail  $OS_METADATA_URL > $OS_META_DATA
if [ $? -eq 0 ] ; then
    OCCI=`echo "import json
print json.loads(open(\"$OS_META_DATA\").read())[\"uuid\"]" | python`
else
    should_umount=0
    # OpenNebula
    mount | grep "^$ONE_CONTEXT_DEVICE" > /dev/null
    if [ $? -eq 0 ] ; then
        # already mounted, get the mount point
        MOUNT_POINT=`mount | grep "^$ONE_CONTEXT_DEVICE" | sed 's/.* on \([^ ]*\) type .*/\1/'`
    else
        # create temporary mount point and mount the sr0
        MOUNT_POINT=`mktemp -d`
        mount $ONE_CONTEXT_DEVICE $MOUNT_POINT
        should_umount=1
    fi
    . $MOUNT_POINT/$ONE_CONTEXT_SCRIPT
    if [ $should_umount -eq 1 ] ; then
        umount $ONE_CONTEXT_DEVICE
        rm -rf $MOUNT_POINT
    fi
fi

rm -f $OS_META_DATA

if [ "x$OCCI" = "x" ] ; then
    echo "Unable to continue without the OCCI uuid"
fi

# Get meta-data from our server
# First check that our metadata is there
curl $EXTRA_CURL_ARGS --retry 3 --retry-delay 0 --silent --fail \
     -X GET $METADATA_URL/$OCCI
if [ $? -ne 0 ] ; then
    echo "Unable to continue without meta-data"
    echo "Failed command: curl $EXTRA_CURL_ARGS -X GET $METADATA_URL/$OCCI"
    curl $EXTRA_CURL_ARGS -X GET $METADATA_URL/$OCCI
    exit 1
fi

# extra ssh-keys
mkdir -p ~/.ssh
curl $EXTRA_CURL_ARGS --silent --fail -X GET $METADATA_URL/$OCCI/ssh-key >> .ssh/authorized_keys

# contextualization repo
if [ -d $CONTEXTUALIZER_PATH ] ; then
    rm -rf $CONTEXTUALIZER_PATH
fi
mkdir -p  `dirname $CONTEXTUALIZER_PATH`
git_repo=`curl $EXTRA_CURL_ARGS --silent --fail -X GET $METADATA_URL/$OCCI/context-repo`
if [ $? -ne 0 ] ; then
    echo "Unable to continue without contextualization repo"
    exit 1
fi
# XXX branches anyone?
git clone $git_repo $CONTEXTUALIZER_PATH

# contextualization data
curl $EXTRA_CURL_ARGS --silent --fail -X GET $METADATA_URL/$OCCI/context-data | $CONTEXTUALIZER_PATH/contextualize

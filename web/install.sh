#! /bin/bash

TARGET=$1

CONFIG=$(dirname $(pwd))/prod/consistency_config.json

if [ "$USER" = "dynamo" ]
then
    DEFAULT=/var/www/html/dynamo/consistency
else
    DEFAULT=$HOME/public_html/ConsistencyCheck
fi

if [ -z $TARGET ]
then

    TARGET=$DEFAULT
    echo "No target passed. Installing to default location: $TARGET"

elif [ "$TARGET" = "-h" -o "$TARGET" = "--help" ]
then

    echo ""
    echo "  Usage: $0 DIRECTORY"
    echo ""
    echo "  Installs webpage files into target directory."
    echo "  (Default: $DEFAULT)"
    echo ""
    exit 0

fi

test -d $TARGET || mkdir -p $TARGET

test -f $TARGET/stats.db || cat $0/maketables.sql | sqlite3 $TARGET/stats.db

cp output.html stats.php stylin.css explanations.html sorttable.js $TARGET
test -f $TARGET/consistency_config.json || ln -s $CONFIG $TARGET/consistency_config.json

if [ "$USER" != "dynamo" ]
then
    sed -i 's@<body>@<body> <p style="color:#ff0000;font-weight:bold;font-size:200%;">Note: As we finish commissioning of US T2 sites, this is transistioning into a development/test instance of the webpage. See the production summary <a href="http://dynamo.mit.edu/consistency/">here</a>.</p>@' $TARGET/output.html
fi

exit $?

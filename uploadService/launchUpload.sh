#!/bin/bash  -x

cmd='screen -L -Logfile upload.log -S upload -dm gunicorn --workers=4 --threads=10 --worker-class=gthread uploadServer:app'
$cmd &


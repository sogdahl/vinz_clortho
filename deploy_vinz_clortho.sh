#!/bin/bash

pushd /home/vdatas/git/vinz_clortho

sudo service vinz-clortho-web stop
sudo service vinz-clortho stop

git pull origin ${1:-master}
git checkout ${1:-master}
git pull origin ${1:-master}

chmod +x vinz_clortho
chmod +x run.py
sudo cp -R * /opt/vinz_clortho/
sudo service vinz-clortho start
sudo service vinz-clortho-web start

popd

#!/bin/bash

pushd /home/vdatas/git/vinz_clortho

sudo service vinz-clortho-web stop
sudo service vinz-clortho stop

git clean -f
git reset --hard
git pull origin ${1:-master}

chmod +x vinz_clortho
chmod +x run.py
sudo rsync -av . /opt/vinz_clortho/ --exclude setup/ --exclude .git/ --exclude .gitignore
sudo service vinz-clortho start
sudo service vinz-clortho-web start

popd

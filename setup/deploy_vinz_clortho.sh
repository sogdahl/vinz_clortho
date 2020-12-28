#!/bin/bash

pushd /home/vdatas/git/vinz_clortho

sudo systemctl stop vinz-clortho-web
sudo systemctl stop vinz-clortho

git clean -f
git reset --hard
git pull origin ${1:-master}

chmod +x vinz_clortho
chmod +x wsgi.py
sudo rsync -av --delete --quiet . /opt/vinz_clortho/ --exclude setup/ --exclude .git/ --exclude .gitignore
sudo systemctl start vinz-clortho
sudo systemctl start vinz-clortho-web

popd

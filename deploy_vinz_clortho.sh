#!/bin/bash

pushd /home/vanguardds/git/vinz_clortho

sudo service vinz_clortho stop

git pull origin ${1:-master}
git checkout ${1:-master}
git pull origin ${1:-master}

chmod +x vinz_clortho.py
sudo cp -R * /etc/vinz_clortho/
sudo service vinz_clortho start

popd

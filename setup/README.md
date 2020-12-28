Steps needed to set up Vinz Clortho on a new system.  Default logging is into /var/log/vinz_clortho/vinz_clortho.log

1. Create excuting user (e.g. vdatas) with appropriate permissions

2. Make sure /etc/hostname has the correct hostname

3. Make sure the following are installed and running
   a. MongoDB (https://docs.mongodb.com/manual/tutorial/install-mongodb-on-ubuntu/)
   b. Python3 & pip (apt-get install -y python3 pip)
   c. Everything in requirements.txt (pip install -r requirements.txt)
   d. gunicorn
   e. nginx

4. Create /var/log/vinz_clortho directory with propermissions for user of (1) to write to

5. Copy vinz-clortho.service and vinz-clortho-web.service scripts from this directory into /etc/systemd/system/

6. Inside /etc/systemd/system/vinz-clortho.service and vinz-clortho-web.service
   a. Update User variable to be the user of (1)
   b. In vinz-clortho.service, update Group to be user group of (1)

7. Run the following to start the daemons and add them to start on system start-up
   a. sudo systemctl daemon-reload
   b. sudo systemctl start vinz-clortho
   c. sudo systemctl enable vinz-clortho
   d. sudo systemctl start vinz-clortho-web
   e. sudo systemctl enable vinz-clortho-web

8. Copy SSL cert (.pem) into /opt/vinz_clortho (NOT PROVIDED HERE)

9. Copy the file from nginx/vinz-clortho-web
   a. Copy into /etc/nginx/sites-available
   b. Edit /etc/nginx/sites-available to point to the correct SSL cert location
   c. Link with sudo ln -s /etc/nginx/sites-available/vinz-clortho-web /etc/nginx/sites-enabled
   d. Restart nginx service with "sudo systemctl restart nginx"

10. Copy deploy_vinz_clortho.sh in this directory to ~/ or wherever it should live

11. Update deploy_vinz_clortho.sh to point the 'pushd' command to where your git repository is

12. (Optional) Update the branch from 'master' to whatever is appropriate

13. Run command to update from git
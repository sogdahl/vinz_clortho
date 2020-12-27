Steps needed to set up Vinz Clortho on a new system.  Default logging is into /var/log/vinz_clortho/vinz_clortho.log

1. Create excuting user (e.g. vdatas) with appropriate permissions

2. Make sure /etc/hostname has the correct hostname

3. Make sure MongoDB is installed and running

4. Create /var/log/vinz_clortho directory with propermissions for user of (1) to write to

5. Copy vinz-clortho and vinz-clortho-web scripts from this directory into /etc/init.d

6. Inside /etc/init.d/vinz-clortho and vinz-clortho-web, Update DAEMON_USER variable to be the user of (1)

7. Run the following to add the daemons to start on system start-up
   a. "update-rc.d vinz-clortho defaults"
   b. "update-rc.d vinz-clortho-web defaults"

8. Enable the services with the following
   a. "sudo service vinz-clortho start"
   b. "sudo service vinz-clortho-web start"

9. Copy deploy_vinz_clortho.sh in this directory to ~/ or wherever it should live

10. Update deploy_vinz_clortho.sh to point the 'pushd' command to where your git repository is

11. (Optional) Update the branch from 'master' to whatever is appropriate

12. Run command to update from git
# KDCam
Home security camera monitoring application, applying intelligent algorithms to captured videos to display any noteworthy activity in a clear and concise format.

***Overview***

Designed to run on a TinkerBoard, Raspberry Pi, or similar - connected to a network camera, which is configured to save video files into the `video_pending` folder listed in `settings_Template.json`.  Note that you need to take `settings_Template.json`, rename it replacing `_Template` with your computer's hostname, and set the various parameters (especially folder paths) to appropriate values for your system.

***Requirements***

This software was written with Python 3.7 and OpenCV 3.4.1.  It is recommended that you use the latest versions to ensure compatibility.  Instructions can be found online for installing OpenCV and setting appropriate bindings for it to work with Python.

The application is written on the assumption that it will always be running.  As such, it should be configured to safe_start itself every few minutes, such that it will be restarted in case of any critical errors.  On Ubuntu Linux, this can be configured easily by running the command `crontab -e`, and adding the following line to the end of the file: `*/5 * * * * python3 /home/usename/KDCam/main.py 'safe_start'`.  This will automatically attempt to start the application every 5mins.  If it is already running, this new instance will exit immediately.

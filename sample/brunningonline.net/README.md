# Attribution
* SysTrayIcon.py taken from http://www.brunningonline.net/simon/blog/archives/SysTrayIcon.py.html
* Icons added from https://www.iconfinder.com/iconsets/fugue with credit to [Yusuke Kamiyamane](http://p.yusukekamiyamane.com/) under CC 3.0

# Building
Building to win32 single exe requires this command: `pyinstaller -w -F --add-binary if_balloon_left_11473.ico;. --add-binary if_mobile_phone_exclamation_12167.ico;. --add-binary if_mobile-phone-cast_26738.ico;. --add-binary if_mobile-phone-medium_58312.ico;. --add-binary if_mobile-phone-off_26739.ico;. --add-binary if_network-cloud_46146.ico;. --add-binary if_plug-connect_58341.ico;. --add-binary if_mobile_phone_12172.ico;. --add-binary if_door-open-out_26228.ico;. -i if_mobile_phone_12172.ico SysTrayIcon.py`
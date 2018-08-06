# Attribution
* SysTrayIcon.py taken from http://www.brunningonline.net/simon/blog/archives/SysTrayIcon.py.html
* Icons added from https://www.iconfinder.com/iconsets/fugue with credit to [Yusuke Kamiyamane](http://p.yusukekamiyamane.com/) under CC 3.0
* Using ideas from sample code for pywin32 downloaded from https://sourceforge.net/projects/pywin32/files/pywin32/

# Setting Up
1. (optional for development environment) Create virtualenv of this directory: 
`virtualenv .`
1. (optional for development environment) Switch into the virtualenv by `cd` and `scripts\activate` or `scripts\activate.bat` in that directory
1. Depending on whether to set up for headless server or with win32 GUI, install the modules using the appropriate requirements file:
`pip install -r requirements.txt` or
`pip install -r requirements-win32.txt`

# Building
Headless server use can skip this step.  Building to win32 single exe requires this command: 
`pyinstaller smsgateway.spec`

# Running
* For headless server, run the `sgserver.py` file using `python sgserver.py [options]`.  Typing `python sgserver.py -h` will show the help.
* For win32 GUI, look in the `dist` folder for the `.exe` that was generated

# Using the API
## Sending Messages
Send your text message to the running server at http://servername/v1/sendsms using a POST with a JSON encoded message containing:
```JSON
{
    "key": "Your secret key configured for the server",
    "number": "The phone number",
    "message": "The message"
}
```
The call returns with the status in JSON containing the 1) reference number, 2) status, 3) the original message.

## Checking Messages
Check on the status of the message by sending a GET request to http://servername/v1/smsstatus/referencenumber
* A JSON is returned containing the 1) reference number, 2) status, 3) the original message
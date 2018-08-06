#!/usr/bin/env python
import multiprocessing, logging, time, os, sys, getopt, signal
from threading import Thread
import tornado.ioloop
import tornado.web
from tornado_json.application import Application
from tornado_json.routes import get_routes
import sgmodem
from sendsms import v1 as sendsms
import sgdatabase

counter = 0
web_server = None
web_server_thread = None
modem_queue = multiprocessing.Queue()
db_queue = multiprocessing.Queue()
exit_event = multiprocessing.Event()
ipipe, opipe = multiprocessing.Pipe()
modemServer = None
stop_db_server = False
log = logging.getLogger('sgserver.server')
requestID = 0
default_settings = {
    'com_port':'COM3',
    'web_port':'8888',
    'keyprotection':'0',
    'key': os.urandom(40).encode('hex'),
    'autostart': '0',
    'min_send_interval':'10'
    }

exe_path = ((os.path.dirname(sys.executable) + '/') if getattr(sys, 'frozen', False) else '')
log_format = '%(asctime)s - PID:%(process)d - %(levelname)s:%(name)s:%(funcName)s: %(message)s'
# set logLevel to logging.DEBUG for debugging and uncomment logging.basicConfig statement
logLevel = logging.WARNING
rootLogLevel = logging.WARNING
rootLogConfig = dict(filename=(exe_path+"main.log"), level=rootLogLevel, format=log_format)
modem_logConfig = dict(filename=exe_path+'modem.log', format=log_format)
# use this if we want to see all debugging output on stdout
# rootLogConfig = dict(format=log_format)
# modem_logConfig = dict(format=log_format)

class Settings(object):
    def __init__(self, database, logLevel=logging.WARNING):
        self.log = logging.getLogger('sgserver.Settings')
        self.log.setLevel(logLevel)
        self.database = database
        self.defaults = {}
        self.settings = {}
    
    def save(self, key, value):
        self.settings[key] = value
        data = {'setting':key, 'value':value}
        self.log.debug('Saving {}={} to database'.format(key,value))
        self.database.queue.put((sgdatabase.PUT, ('setting', 'settings', data)))

    def get(self, key):
        return self.settings[key]

    # get settings from database and update with defaults
    def set_defaults(self, defaults=None):
        global default_settings
        self.defaults = defaults or default_settings

        # get the existing settings from the database
        self.log.debug('Getting existing settings from the database')
        for setting in self.database.get(None,'settings'):
            self.log.debug('Found {}={}'.format(setting['setting'],setting['value']))
            self.settings[setting['setting']] = setting['value']

        # update the settings with any missing default settings
        for default in self.defaults:
            if self.settings.get(default) is None:
                self.log.debug('Saving missing defaults {}={}'.format(default,self.defaults[default]))
                # save the missing setting with the default one
                self.settings[default] = self.defaults[default]
                # save the missing setting into the database as well
                self.save(default, self.defaults[default])
   
class MainHandler(tornado.web.RequestHandler):
    def get(self):
        global counter
        self.write("SMS Gateway<p>This server has been accessed {} times, with {} times coming from the API".
            format(counter+sendsms.counter,sendsms.counter))
        counter = counter + 1

def make_app(sg_settings):
#    routes = get_routes(sendsms)
    return Application(routes=[
        (r"/",MainHandler),
        (r"/v1/sendsms",sendsms.SendSMSHandler),
        (r"/v1/smsstatus/([0-9]+)",sendsms.GetStatusHandler),
        ], settings={"requestID":requestID,
                    "db_queue":db_queue, 
                    "modem_queue":modem_queue,
                    "ipipe":ipipe,
                    "settings":sg_settings})

def start_server(sg_settings, db_server, level=None, mlogConfig=None):
    def start():
        def stop_check():
#            log.debug('Stop check is called')
            if exit_event.is_set():
                stop_server()
                # We only stop the db_server as well if True.
                # This allows for a GUI to continue running and have 
                # access to the settings database
                if stop_db_server:
                    db_server.stop_thread()

        global web_server, requestID
        log.debug('Thread starting')
        try:
            # update to the correct index aka requestID
            db_queue.put((sgdatabase.UPDATE_INDEX, 'sms'))
            db_server.index_updated.wait()
            requestID = db_server.index

            web_server = tornado.httpserver.HTTPServer(make_app(sg_settings))
            web_server.listen(int(sg_settings.get('web_port')))
            tornado.ioloop.PeriodicCallback(stop_check,5000).start()
            tornado.ioloop.IOLoop.instance().start()
        except Exception as e:
            log.error('Exception ocurred %s:%s', e.message, e.args, exc_info=True)
            raise e
        log.debug('Thread exiting')

    global web_server_thread, modemServer
    
    level = level or logLevel
    log.setLevel(level)
    log.debug('Modem connecting')
    mlogConfig = mlogConfig or modem_logConfig

    # Startup Modem Server
    exit_event.clear()
    modemServer = sgmodem.ModemServer(modem_queue, db_queue, exit_event, sg_settings.get('com_port'),
        sg_settings.get('min_send_interval'),
        level, mlogConfig)
    modemServer.daemon = True
    modemServer.name = 'ModemServer'
    modemServer.start()
    log.debug('Modem connected and ready')

    # Startup Tornado Web Server
    log.debug('Server starting')
    web_server_thread = Thread(target=start,name='TornadoWebThread')
    web_server_thread.start()
    log.debug('Server started')

def stop_server(*args):
    global web_server, web_server_thread, modemServer, exit_event

    log.debug('Server stopping')
    web_server.stop()
    ioloop = tornado.ioloop.IOLoop.instance()
    ioloop.add_callback(ioloop.stop)
#    web_server_thread.join()
    log.debug('Server stopped')

    log.debug('Modem stopping')
    exit_event.set()
    log.debug('Modem stopped')

def init(argv):
    port, com, interval, keyprotection, key, dbfile = get_args(argv)

    logging.basicConfig(**rootLogConfig)

    # Startup Database Server and get settings
    if dbfile is None:
        db_server = sgdatabase.SMSDatabase(logLevel=logLevel)
    else:
        db_server = sgdatabase.SMSDatabase(url='sqlite:///'+dbfile,logLevel=logLevel)
    db_server.start_thread(db_queue, opipe)
    sg_settings = Settings(db_server, logLevel=logLevel)
    sg_settings.set_defaults()

    save_arg_settings(sg_settings, port, com, interval, keyprotection, key)

    return db_server, sg_settings

def usage():
    print('\
        -p --port <web port> : web server port\n\
        -c --com <com port> : serial or comm port\n\
        -t --interval <time> : time between each SMS in sec\n\
        -a --keyprotection <1:0>: enable/disable secret key only access. If not specified, existing database setting or default setting of 0 will be used\n\
        -d --dbfile <file> : location of database file. If not specified, a file database.db will be created in current directory\n\
        -k --keyfile <file> : location of a file containing the secret key.  If not specified but keyprotection is enabled, a random one will be generated and saved in the database\n\
        -l --logdir <dir> : location where the log files will be written to.  If not specified, the current directory will be used\n\
        -v : enable debugging output')

def get_args(argv):
    try:
        opts, args = getopt.getopt(argv, 
                                "hp:c:t:a:d:k:l:v", [
                                'help',
                                'port=',
                                'com=',
                                'interval=',
                                'keyprotection='
                                'dbfile=',
                                'keyfile=',
                                'logdir=',
                                'debug'
                                ])
    except getopt.GetoptError:
        print('Incorrect settings passed')
        usage()
        sys.exit(2)
    
    port = com = interval = keyprotection = dbfile = key = None

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        if opt in ("-p", "--port"):
            port = arg
        elif opt in ("-c", "--com"):
            com = arg
        elif opt in ("-t", "--interval"):
            interval = arg
        elif opt in ("-a", "--keyprotection"):
            keyprotection = arg
        elif opt in ("-d", "--dbfile"):
            dbfile = arg
        elif opt in ("-k", "--keyfile"):
            key = open(arg,'r').readline()
        elif opt in ("-l", "--logdir"):
            global exe_path, rootLogConfig, modem_logConfig
            exe_path = arg
            rootLogConfig['filename']=exe_path+'/main.log'
            modem_logConfig['filename']=exe_path+'/modem.log'
        elif opt in ("-v", "--debug"):
            global logLevel
            logLevel = logging.DEBUG
    
    return port, com, interval, keyprotection, key, dbfile

def save_arg_settings(sg_settings, port, com, interval, keyprotection, key):
    if port is not None:
        sg_settings.save('web_port', str(port))
    if com is not None:
        sg_settings.save('com_port', str(com))
    if interval is not None:
        sg_settings.save('min_send_interval', str(interval))
    if keyprotection:
        sg_settings.save('keyprotection',str(keyprotection))
    if key is not None:
        sg_settings.save('key', str(key))

def signal_exit(*args):
    exit_event.set()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_exit)
    signal.signal(signal.SIGTERM, signal_exit)

    stop_db_server = True # allow webserver upon stopping to also stop db server
    db_server, sg_settings = init(sys.argv[1::])

    start_server(sg_settings, db_server)
    web_server_thread.join()

    log.debug('Waiting 10 secs for everything to shutdown')
    time.sleep(10) # wait 10 secs
    print 'Bye Now'
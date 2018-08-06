import sys, os, multiprocessing, logging
from threading import Thread, Event, Lock
import dataset

log = logging.getLogger('sgdatabase.SMSDatabase')

# commands that the SMS Database server can receive to process
GET=0
PUT=1
EXIT=2
UPDATE_INDEX=3
GET_VALUE=4
GET_ALL=5

class SMSDatabase(multiprocessing.Process):
    def __init__(self, 
                url = 'sqlite:///' + ((os.path.dirname(sys.executable) + '/') if getattr(sys, 'frozen', False) else '')+"database.db",
                tablenames=['sms','settings'],
                logLevel=logging.WARNING):
        self.url = url
        self.tablenames = tablenames
        self.db = None
        self.tables = {}
        self.queue = None
        self.pipe = None
        self.thread = None
        self.index = 0
        self.index_updated = Event()
        self.val = None
        self.val_lock = Lock()
        self.val_updated = Event()
        log.setLevel(logLevel)

    def connect(self, url=None, tablenames=None):
        url = url or self.url
        tablenames = tablenames or self.tablenames
        self.db = dataset.connect(url)
        for name in tablenames:
            self.tables[name] = self.db.get_table(name)
            print self.tables[name] # need this extra print to initialize the database file with the table if empty initially

    def get_one(self, search, tablename):
        self.val_lock.acquire()
        self.val_updated.clear()
        self.queue.put((GET_VALUE,(search, tablename)))
        self.val_updated.wait()
        val = self.val
        self.val_lock.release()
        return val

    def get(self, search, tablename):
        val = []
        self.val_lock.acquire()
        self.val_updated.clear()
        self.queue.put((GET_ALL,(search, tablename)))
        self.val_updated.wait()
        for i in self.val:
            val.append(i)
        self.val_lock.release()
        return val
   
    def update_loop(self, queue, pipe):
        self.connect()

        while True:
            action, payload = self.queue.get()

            # Exit requested
            if action == EXIT:
                log.debug("Exiting")
                break
            # Put requested
            elif action == PUT:
                log.debug("Received put request")
                key, table, data = payload
                self.tables[table].upsert(data, [key])
                log.debug("Put request successful")
            # Update the index number used for getting the reference numbers
            elif action == UPDATE_INDEX:
                table = payload
                if self.tables[table].count():
                    self.index = self.tables[table].find_one(order_by='-id')['id']
                else:
                    self.index = 0
                self.index_updated.set()
            elif action == GET_VALUE:
                search, table = payload
                self.val = self.tables[table].find_one(**search)
                self.val_updated.set()
            elif action == GET_ALL:
                search, table = payload
                if search:
                    results = self.tables[table].find(**search)
                else: # is None
                    results = self.tables[table].find()
                self.val = []
                for i in results:
                    self.val.append(i)
                self.val_updated.set()
            else: # Get request
                log.debug("Received get request")
                search, table = payload
                results = self.tables[table].find_one(**search)
                log.debug("Get request successful for %s",search)
                self.pipe.send(results)
                log.debug("Results sent for %s",search)


    def start_thread(self, queue=None, pipe=None):
        # make sure to start the thread with a valid queue and response pipe
        if queue is None:
            if self.queue is None:
                log.error('No queue received to start')
                raise Exception
            queue = self.queue
        else:
            self.queue = queue
        if pipe is None:
            if self.pipe is None:
                log.error('No pipe received to start')
                raise Exception
            pipe = self.pipe
        else:
            self.pipe = pipe

        log.debug('Server starting')
        self.thread = Thread(target=self.update_loop, args=(queue, pipe), name='SMSDatabaseThread')
        self.thread.start()
        log.debug('Server started')

    def stop_thread(self):
        self.queue.put((EXIT,None))
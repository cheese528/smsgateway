import multiprocessing, Queue, types, logging, time, threading, weakref, sys, os
from gsmmodem.util import parseTextModeTimeStr
import gsmmodem
from serial import SerialException
from gsmmodem.exceptions import CommandError, InvalidStateException, CmeError, CmsError, InterruptedException, TimeoutException, PinRequiredError, IncorrectPinError, SmscNumberUnknownError
import sgdatabase

UNKNOWNERROR= -99 # Unknown error
CMS_ERROR = -4 # Modem reported CMS Error
CME_ERROR = -3 # Modem reported CMS Error
MODEMDISCONNECTED = -2 # Modem is not connected so message will be ignored
QUEUED = -1 # Message has been enqueued into modem queue for processing
ENROUTE = gsmmodem.modem.SentSms.ENROUTE # Status indicating message is still enroute to destination
DELIVERED = gsmmodem.modem.SentSms.DELIVERED # Status indicating message has been received by destination handset
FAILED = gsmmodem.modem.SentSms.FAILED # Status indicating message delivery has failed

# bug fix to support T35i modem
def _deleteStoredSms(self, index, memory=None):
    self._setSmsMemory(readDelete=memory)
    self.write('AT+CMGD={0}'.format(index))
    
class ModemServer(multiprocessing.Process):

    def __init__(self, input_queue, output_queue, exitEvent, commPort, min_send_interval=None, logLevel=logging.WARNING, logConfig={}):
        multiprocessing.Process.__init__(self)
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.exit = exitEvent
        self.commPort = commPort
        self.modem = None
        self.log = None
        self.logLevel = logLevel
        self.logConfig = logConfig
        self.sentSms = dict()
        self.min_send_interval = min_send_interval or 0
        self.connected = False

    def connect(self, port, baudrate=115200):
        try:
            self.log.debug('Connecting modem')
            self.modem = gsmmodem.GsmModem(port, baudrate, smsStatusReportCallback=self.msgSentCallback, requestDelivery=False)
            self.modem.smsTextMode = False
            self.reset_logger(self.modem.log, logConfig=self.logConfig)
            self.modem.deleteStoredSms = types.MethodType(_deleteStoredSms, self.modem) # bug fix to support T35i modem
            self.modem.connect()
            self.connected = True
            self.log.debug('Connected modem')
        except SerialException as e:
            self.log.warn("Unable to connect to COM port=%s.  Please check your settings.  Only loopback SMS will work. msg=%s", self.commPort, e.message)

    def close(self):
        if self.connected:
            self.modem.close()
            self.connected = False

    def sendMsg(self, number, text, requestID):
        try:
            sms = self.modem.sendSms(number, text)
            self.log.debug('Message sent with status=%d', sms.status)
        except CmsError as e:
            self.log.warn('CMS error occured: %s %s', e.message, e.args, exc_info=True)
            sms = None
            self.output_queue.put((sgdatabase.PUT, ('id', 'sms', dict(id=requestID, request_status=CMS_ERROR))))
        except CmeError as e:
            self.log.warn('CME error occured: %s %s', e.message, e.args, exc_info=True)
            sms = None
            self.output_queue.put((sgdatabase.PUT, ('id', 'sms', dict(id=requestID, request_status=CME_ERROR))))
        except Exception as e:
            self.log.error('Unknown error occured: %s %s', e.message, e.args, exc_info=True)
            sms = None
            self.output_queue.put((sgdatabase.PUT, ('id', 'sms', dict(id=requestID, request_status=UNKNOWNERROR))))                                
        return sms
        

    def msgSentCallback(self, status):
        self.log.debug('status=%d reference=%d number=%s timeSent=%s timeFinalized=%s deliveryStatus=%d',
                        status.status,
                        status.reference,
                        status.number,
                        str(status.timeSent),
                        str(status.timeFinalized),
                        status.deliveryStatus)

        requestID = self.sentSms[status.reference][0]
        request_status = self.sentSms[status.reference][1].status

        # Basic sanity check to make sure the status report is for the message sent originally
        if not (self.sentSms[status.reference][1].number == status.number):
            self.log.warn('Sent SMS phone number does not match delivery report %s != %s', 
                        self.sentSms[status.reference][1].number,status.number)

        # Update the SMS database with the details from the status report
        data = {"id":requestID, "request_status": request_status, 
                "status":status.status, "reference":status.reference, "number":status.number, 
                "timeSent":status.timeSent, "timeFinalized":status.timeFinalized, 
                "deliveryStatus":status.deliveryStatus}

        self.output_queue.put((sgdatabase.PUT, ('id', 'sms', data)))

    def _msgSentCallbackTest(self):
        status=gsmmodem.modem.StatusReport(self.modem, status=0, number='0', reference=256, 
                                            timeSent=parseTextModeTimeStr('00/01/01,00:00:00+00'), 
                                            timeFinalized=parseTextModeTimeStr('00/01/01,00:00:00+00'), 
                                            deliveryStatus=0)
        self.sentSms[status.reference][1].report = status
        self.msgSentCallback(status)
    
    def reset_logger(self, log, logLevel=None, logConfig={}):
        log.propagate = False

        if logLevel is not None:
            log.setLevel(logLevel)

        try:
            filename = logConfig['filename']
        except KeyError:
            filename = None
            pass

        try:
            formatter = logConfig['format']
        except KeyError:
            formatter = None
            pass

        try:
            level = logConfig['level']
            log.setLevel(level)
        except KeyError:
            pass

        for handler in log.handlers:
            log.removeHandler(handler)
        if filename is not None:
            hdl = logging.FileHandler(filename)
        else:
            hdl = logging.StreamHandler()
        if formatter is not None:
            hdl.setFormatter(logging.Formatter(formatter))
        log.addHandler(hdl)

    def run(self):
        self.log = logging.getLogger('sgmodem.server.ModemServer')
        self.reset_logger(self.log, logLevel=self.logLevel, logConfig=self.logConfig)
        self.log.debug('logConfig is {}'.format(self.logConfig))
        try:
            # connect to the modem
            self.connect(self.commPort)

            # loop the input queue messages to send
            try:
                last_sent_time = time.time()
                while not self.exit.is_set() or not self.input_queue.empty():
                    try:
                        number, text, requestID = self.input_queue.get(timeout=5)
                        remaining_time = int(self.min_send_interval) + last_sent_time - time.time()
                        if (remaining_time > 0):
                            self.log.debug("Minimum send interval of %ss not yet elapsed, sleeping %ds",
                                self.min_send_interval, remaining_time)
                            time.sleep(remaining_time)
                        self.log.debug('Sending to number=%s, message=%s', number, text)
                        if number == '0': # test sending
                            self.sentSms[256] = (requestID, gsmmodem.modem.SentSms(number, text, 256))
                            threading.Thread(target=self._msgSentCallbackTest).start()
                        else:
                            if not self.connected:
                                self.output_queue.put((sgdatabase.PUT, ('id', 'sms', dict(id=requestID, request_status=MODEMDISCONNECTED))))
                                self.log.warn('Modem is not connected.  Message is ignored')
                                continue
                            sms = self.sendMsg(number, text, requestID)
                            if sms is None:
                                self.log.warn('sendMsg failed.  Message is ignored')
                                pass
                            else:
                                self.sentSms[sms.reference] = (requestID, sms)
                                self.output_queue.put((sgdatabase.PUT, ('id', 'sms', dict(id=requestID, request_status=ENROUTE))))
                        last_sent_time = time.time()
                    except Queue.Empty:
                        pass
                    except KeyboardInterrupt:
                        if not self.exit.is_set():
                            self.exit.set()
                        self.log.info('Ctrl-C received, exiting')
                        break
            except Exception as e:
                self.log.error("An error inside the send loop %s %s", e.message, e.args, exc_info=True)
                raise e
            finally:
                self.close()
        except Exception as e:
            self.log.error('An error occurred. Modem process will exit now. %s %s', e.message, e.args, exc_info=True)
            raise e
        finally:
            self.log.debug('Exiting')

if __name__ == "__main__":
    iq = Queue.Queue()
    oq = Queue.Queue()
    evt = multiprocessing.Event()
    modem = ModemServer(iq, oq, evt, 'COM4')
    modem.run()
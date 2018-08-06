import multiprocessing, logging
from tornado_json.requesthandlers import APIHandler
from tornado_json import schema
import sgdatabase
import sgmodem

counter = 0

class SendSMSHandler(APIHandler):
    @schema.validate(
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "number": {"type": "string"},
                "message": {"type": "string"},
            }
        },
        input_example={
            "key": "Your secret API key",
            "number": "Phone number to send to",
            "message": "Your SMS message to send",
        },
        output_schema={
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "status": {"type": "string"},
                "message": {"type": "string"},
            }
        },
        output_example={
            "reference": "SMS send request reference number",
            "status": "The status of your request",
            "message": "",
        },
    )
    def post(self):
        global counter
        counter += 1
        keyprotection = int(self.application.settings.get("settings").get('keyprotection'))
        if keyprotection:
            if self.application.settings.get("settings").get('key') != self.body["key"]:
                return {
                    "reference": "-1",
                    "status": "-1",
                    "message": "Invalid key",
                }
        number, message = self.body["number"], self.body["message"]
        requestID = self.application.settings.get("requestID") + 1
        self.application.settings['requestID'] = requestID
        sms = {'id':requestID, 'request_status': sgmodem.QUEUED, 'number': number, 'message': message}
        self.application.settings.get("db_queue").put((sgdatabase.PUT, ('id', 'sms', sms)))
        self.application.settings.get("modem_queue").put((number, message, requestID))
        return {
            "reference": "{}".format(requestID),
            "status": "{}".format(sgmodem.QUEUED),
            "message": "{}".format(message)
        }

class GetStatusHandler(APIHandler):
    @schema.validate(
        output_schema={
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "status": {"type": "string"},
                "message": {"type": "string"},
            }
        },
        output_example={
            "reference": "SMS send request reference number",
            "status": "The status of your request, 0 is pending, 1 is success, and 2 is failed",
            "message": "The message you sent",
        },
    )
    def get(self, requestID):
        global counter
        counter += 1
        keyprotection = int(self.application.settings.get("settings").get('keyprotection'))
        if keyprotection:
            key = self.get_argument('key')
            if self.application.settings.get("settings").get('key') != key:
                return {
                    "reference": "-1",
                    "status": "-1",
                    "message": "Invalid key",
                }
        req = dict(id=int(requestID))
        self.application.settings.get('db_queue').put((sgdatabase.GET, (req,'sms')))
        data = self.application.settings.get('ipipe').recv()
        if data is None:
            return { 
                "reference": "{}".format(requestID),
                "status": "-1",
                "message": "INVALID REFERENCE"
            }
        return {
            "reference": "{}".format(requestID),
            "status": '{}'.format(data['request_status']),
            "message": "{}".format(data['message'])
        }


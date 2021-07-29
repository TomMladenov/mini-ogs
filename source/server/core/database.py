import datetime
import threading
import time
from influxdb import InfluxDBClient


class Database(threading.Thread):

    def __init__(self):
        super(Database, self).__init__()

        self.systems = []
        self.dbclient = InfluxDBClient(host="127.0.0.1", port=8086, username="root", password="root", database="ogs")

        self.running = True

    def addSystem(self, sys):
        self.systems.append(sys)

    def logStatus(self, id, fields):
     
        json_body = [{
                        "measurement": id,
                        "time": datetime.datetime.utcnow(),
                        "fields": fields
                    }]

        self.dbclient.write_points(json_body)


    def stop(self):
        self.running = False


    def run(self):
        while self.running:
            for sys in self.systems:
                self.logStatus(sys.name, sys.getStatus())
            time.sleep(1)

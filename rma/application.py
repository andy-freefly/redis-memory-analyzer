import sys
import fnmatch

from rma.Redis import *
from rma.Scanner import Scanner
from rma.Splitter import *

from rma.rule import *
from rma.reporters import *
from rma.helpers import *
from redis.exceptions import ConnectionError, ResponseError


        # print(r.eval("""
        #     local ret = redis.call("KEYS", "*")
        #     local z = 0
        #     for i = 1, #ret do
        #         local type1 = redis.call("TYPE", ret[i])["ok"]
        #         if type1 ~= "hash" then
        #             redis.call("del", ret[i])
        #             z = z  + 1
        #         end
        #     end
        #     return z
        # """, 0))
        # return


def connect_to_redis(host, port, db=0, password=None):
    """

    :param host:
    :param port:
    :param db:
    :param password:
    :return RmaRedis:
    """
    try:
        redis = RmaRedis(host=host, port=port, db=db, password=password)
        if not check_redis_version(redis):
            sys.stderr.write('This script only works with Redis Server version 2.6.x or higher\n')
            sys.exit(-1)
    except ConnectionError as e:
        sys.stderr.write('Could not connect to Redis Server : %s\n' % e)
        sys.exit(-1)
    except ResponseError as e:
        sys.stderr.write('Could not connect to Redis Server : %s\n' % e)
        sys.exit(-1)
    return redis


def check_redis_version(redis):
    server_info = redis.info()
    version_str = server_info['redis_version']
    version = tuple(map(int, version_str.split('.')))

    if version[0] > 2 or (version[0] == 2 and version[1] >= 6):
        return True
    else:
        return False


class RmaApplication:
    globals = []

    types_rules = {
        REDIS_TYPE_ID_STRING: [],
        REDIS_TYPE_ID_HASH: [],
        REDIS_TYPE_ID_LIST: [],
        REDIS_TYPE_ID_SET: [],
        REDIS_TYPE_ID_ZSET: [],
    }

    def __init__(self, options):
        self.options = options
        self.splitter = SimpleSplitter()
        self.reporter = TextReporter()
        if 'filters' in options:
            if 'types' in options['filters']:
                self.types = options['filters']['types']
            else:
                self.types = None
            if 'behaviour' in options['filters']:
                self.behaviour = options['filters']['behaviour']
            else:
                self.behaviour = 'all'
        else:
            self.types = None
            self.behaviour = 'all'

    def init_globals(self, redis):
        self.globals.append(GlobalKeySpace(redis=redis))

    def init_types_rules(self, redis):
        self.types_rules[REDIS_TYPE_ID_STRING].append(KeyString(redis=redis))
        self.types_rules[REDIS_TYPE_ID_STRING].append(ValueString(redis=redis))
        self.types_rules[REDIS_TYPE_ID_HASH].append(KeyString(redis=redis))
        self.types_rules[REDIS_TYPE_ID_HASH].append(Hash(redis=redis))
        self.types_rules[REDIS_TYPE_ID_LIST].append(KeyString(redis=redis))
        self.types_rules[REDIS_TYPE_ID_LIST].append(List(redis=redis))
        self.types_rules[REDIS_TYPE_ID_SET].append(KeyString(redis=redis))
        self.types_rules[REDIS_TYPE_ID_ZSET].append(KeyString(redis=redis))

    def run(self):
        r = connect_to_redis(host=self.options['host'], port=self.options['port'])

        self.init_globals(redis=r)
        self.init_types_rules(redis=r)

        with Scanner(redis=r, match=self.options['match']) as scanner:
            scanner_limit = self.options['limit'] if 'limit' in self.options else sys.maxsize
            res = scanner.scan(limit=scanner_limit)

            str_res = []
            self.run_global_rules(str_res)

            if self.behaviour == 'all':
                for key, data in res.items():
                    aggregate_patterns = self.get_pattern_aggregated_data(data, key)

                    if key in self.types_rules:
                        str_res.append("Processing {0}".format(type_id_to_redis_type(key)))
                        for rule in self.types_rules[key]:
                            str_res += (rule.analyze(aggregate_patterns))
            elif self.behaviour == 'scanner':
                key_stat = {
                    'headers': ['Match', "Count", "Type", "%"],
                    'data': []
                }
                total = r.total_keys()
                for key, data in res.items():
                    type = type_id_to_redis_type(key)
                    aggregate_patterns = self.get_pattern_aggregated_data(data, key)

                    for k, v in aggregate_patterns.items():
                        key_stat['data'].append([k, len(v), type, floored_percentage(len(v) / total, 2)])

                key_stat['data'].sort(key=lambda x: x[1], reverse=True)
                str_res += ["Keys by types", key_stat]


            self.reporter.print(str_res)

    def run_global_rules(self, str_res):
        str_res.append('Server stat')
        for glob in self.globals:
            str_res += glob.analyze()

        return str_res

    def get_pattern_aggregated_data(self, data, key):
        split_patterns = self.splitter.split(data)

        print("\r\nType %s" % type_id_to_redis_type(key))
        print(split_patterns)

        aggregate_patterns = {item: [] for item in split_patterns}
        for pattern in split_patterns:
            aggregate_patterns[pattern] = list(filter(lambda x: fnmatch.fnmatch(x, pattern), data))

        return aggregate_patterns
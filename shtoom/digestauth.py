# import hashlib instead of md5
#import md5
#import sha
import hashlib
import time
import random

def generate_nonce(bits, randomness=None):
    "This could be stronger"
    if bits%8 != 0:
        raise ValueError("bits must be a multiple of 8")
    nonce = sha.new(str(randomness) + str(time.time()) +
            str(random.random()) ).hexdigest()
    nonce = nonce[:bits/4]
    return nonce

def parse_keqv_list(l):
    """Parse list of key=value strings where keys are not duplicated."""
    parsed = {}
    for elt in l:
        k, v = elt.split('=', 1)
        if v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        parsed[k] = v
    return parsed

class DigestAuthServer:

    def __init__(self, default_realm, algorithm="MD5"):
        self.default_realm = default_realm
        if algorithm != 'MD5':
            raise ValueError("Don't know about algorithm %s"%(algorithm))
        self.algorithm = algorithm
        self._user_hashes = {}

    def get_algorithm_impls(self, algorithm=None):
        # lambdas assume digest modules are imported at the top level
        if algorithm is None:
            algorithm = self.algorithm
        if algorithm == 'MD5':
            H = lambda x: hashlib.md5(x).hexdigest()
        elif algorithm == 'SHA1':
            H = lambda x: hashlib.sha1(x).hexdigest()
        # XXX MD5-sess
        KD = lambda s, d, H=H: H("%s:%s" % (s, d))
        return H, KD

    def add_user(self, user, password, realm=None):
        "add the given user and password"
        H, KD = self.get_algorithm_impls()
        if realm is None:
            realm = self.default_realm
        A1 = H('%s:%s:%s'%(user, realm, password))
        self._user_hashes[(user, realm)] = A1

    def add_user_hash(self, user, A1, realm=None):
        "add the given user with the stated hash"
        if realm is None:
            realm = self.default_realm
        self._user_hashes[(user, realm)] = A1

    def parse_apache_digest_authfile(self, filename):
        "Parse a password file, as generated by htdigest"
        for line in open(filename, 'rU'):
            line = line.strip()
            user, realm, hash = line.split(':')
            self.add_user_hash(user, hash, realm)

    def generate_challenge(self, realm=None):
        if realm is None:
            realm = self.default_realm

        # We should save off the nonce to make sure it's one we've
        # offered already. And check for replay attacks :-(
        chal = 'realm="%s", nonce="%s", ' \
               'algorithm=%s, qop="auth"'%(realm,
                                           generate_nonce(bits=208),
                                           self.algorithm)
        return chal

# Firebird
# username="anthony", realm="TestAuth",
# nonce="9da7db19648f95bd71f26a07b3423d91917b5205", uri="/test/foo",
# algorithm=MD5, response="f61ca0cb8a85e9bd985b7ab808978f1e",
# qop=auth, nc=00000001, cnonce="424a1ed1ddaa76ca"

# Konqi
# username="anthony", realm="TestAuth",
# nonce="7c8bdda0ed44db7de74bee97cec8dfd4fb59af0f", uri="/test/foo",
# algorithm="MD5", qop="auth", cnonce="ODQwMTk=", nc=00000001,
# response="1bebadb47d2aa5eab53cb419b94599f3"

    def check_auth(self, header, method='GET'):
        "Check a response to our auth challenge"
        from urllib3 import parse_http_list
        H, KD = self.get_algorithm_impls()
        resp = parse_keqv_list(parse_http_list(header))
        algo = resp.get('algorithm', 'MD5').upper()
        if algo != self.algorithm:
            return False, "unknown algo %s"%algo
        user = resp['username']
        realm = resp['realm']
        nonce = resp['nonce']
        # XXX Check the nonce is something we've issued
        HA1 = self._user_hashes.get((user,realm))
        if not HA1:
            return False, "unknown user/realm %s/%s"%(user, realm)
        qop = resp.get('qop')
        if qop != 'auth':
            return False, "unknown qop %r"%(qop)
        cnonce, ncvalue = resp.get('cnonce'), resp.get('nc')
        if not cnonce or not ncvalue:
            return False, "failed to provide cnonce"
        # Check the URI is correct!
        A2 = '%s:%s'%(method, resp['uri'])
        noncebit = "%s:%s:%s:%s:%s" % (nonce,ncvalue,cnonce,qop,H(A2))
        respdig = KD(HA1, noncebit)
        if respdig != resp['response']:
            return False, "response incorrect"
        print("all ok")
        return True, "OK"

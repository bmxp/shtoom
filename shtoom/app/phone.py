# Copyright (C) 2004 Anthony Baxter

# The Phone app.

import threading, os.path

from twisted.internet import defer, protocol
from twisted.python import log, threadable

from shtoom.app.interfaces import Application
from shtoom.app.base import BaseApplication
from shtoom.exceptions import CallFailed
from shtoom.audio import FMT_PCMU, FMT_GSM, FMT_SPEEX, FMT_DVI4, getAudioDevice
from shtoom.rtp import RTPProtocol
from shtoom.sdp import SDP, MediaDescription
from shtoom.ui.select import findUserInterface
from shtoom.opts import buildOptions
from shtoom.Options import OptionGroup, StringOption, ChoiceOption

class Phone(BaseApplication):
    __implements__ = ( Application, )

    _startReactor = True

    def __init__(self, ui=None, audio=None):
        # Mapping from callcookies to rtp object
        self._rtp = {}
        # Mapping from callcookies to call objects
        self._calls = {}
        self._pendingRTP = {}
        self._audio = audio
        self._audioFormat = None
        self.ui = ui
        self._currentCall = None
        self._muted = False
        self._rtpProtocolClass = None

    def needsThreadedUI(self):
        return self.ui.threadedUI

    def boot(self, options=None):
        if options is None:
            options = buildOptions(self)
        self.initOptions(options)

        if self.ui is None:
            self.ui = findUserInterface(self, self.getPref('ui'))
        BaseApplication.boot(self)

    def register(self):
        register_uri = self.getPref('register_uri')
        if register_uri is not None:
            self.sip.register()

    def start(self):
        "Start the application."
        self.register()
        if not self._startReactor:
            log.msg("Not starting reactor - test mode?")
            return
        if self.needsThreadedUI():
            threadable.init(1)
            from twisted.internet import reactor
            t = threading.Thread(target=reactor.run, kwargs={
                                'installSignalHandlers':0} )
            t.start()
            self.ui.startUI()
        else:
            from twisted.internet import reactor
            reactor.run()

    def getAuth(self, method, realm):
        self.ui.getString("Please enter user,passwd for %s at %s"%(method, 
                                                                   realm))

    def acceptCall(self, call):
        log.msg("dialog is %r"%(call.dialog))
        if self._audio is None:
            self.openAudioDevice()
        cookie = self.getCookie()
        self._calls[cookie] = call
        d = self._createRTP(cookie, 
                            call.getLocalSIPAddress()[0], 
                            call.getSTUNState())
        self.ui.callStarted(cookie)
        calltype = call.dialog.getDirection()
        if calltype == 'inbound':
            # Otherwise we chain callbacks
            ringingCommand = self.getPref('ringing_command')
            # Commented out until I test it
            if 0 and ringingCommand:
                args = ringingCommand.split(' ')
                cmdname = args[0]
                reactor.spawnProcess(protocol.ProcessProtocol(), cmd, args)
            self.ui.incomingCall(call.dialog.getCaller(), cookie, d)
        elif calltype == 'outbound':
            d.addCallback(lambda x, cookie=cookie: cookie )
        else:
            raise ValueError, "unknown call type %s"%(calltype)
        return d

    def _createRTP(self, cookie, localIP, withSTUN):
        if self._rtpProtocolClass is None:
            rtp = RTPProtocol(self, cookie)
        else:
            rtp = self._rtpProtocolClass(self, cookie)
        self._rtp[cookie] = rtp
        d = rtp.createRTPSocket(localIP,withSTUN)
        return d

    def selectFormat(self, callcookie, sdp):
        md = sdp.getMediaDescription('audio')
        rtpmap = md.rtpmap
        rtp =  self._rtp[callcookie]
        for entry,desc in rtpmap:
            if entry == rtp.PT_pcmu:
                self._audio.selectFormat(FMT_PCMU)
                self._audioFormat = entry
                break
            elif entry == rtp.PT_gsm:
                self._audio.selectFormat(FMT_GSM)
                self._audioFormat = entry
                break
            else:
                raise ValueError, "couldn't set to %r"%entry
        else:
            raise ValueError, "no working formats"

    def getSDP(self, callcookie):
        rtp =  self._rtp[callcookie]
        s = SDP()
        addr = rtp.getVisibleAddress()
        s.setServerIP(addr[0])
        md = MediaDescription()
        s.addMediaDescription(md)
        md.setServerIP(addr[0])
        md.setLocalPort(addr[1])
        fmts = self._audio.listFormats()
        if FMT_GSM in fmts:
            md.addRtpMap('GSM', 8000) # GSM 06.10
        if FMT_PCMU in fmts:
            md.addRtpMap('PCMU', 8000) # G711 ulaw
        if FMT_SPEEX in fmts:
            md.addRtpMap('speex', 8000, payload=110)
            #md.addRtpMap('speex', 16000, payload=111)
        if FMT_DVI4 in fmts:
            md.addRtpMap('DVI4', 8000)
            #s.addRtpMap('DVI4', 16000)
        md.addRtpMap('telephone-event', 8000, payload=101)
        return s

    def startCall(self, callcookie, remoteSDP, cb):
        log.msg("startCall reopening %r %r"%(self._currentCall, self._audio))
        md = remoteSDP.getMediaDescription('audio')
        ipaddr = md.ipaddr or remoteSDP.ipaddr
        remoteAddr = (ipaddr, md.port)
        if not self._currentCall:
            self._audio.reopen()
        log.msg("call Start %r %r"%(callcookie, remoteAddr))
        self._rtp[callcookie].startSendingAndReceiving(remoteAddr)
        self._currentCall = callcookie
        cb(callcookie)

    def endCall(self, callcookie, reason=''):
        rtp = self._rtp.get(callcookie)
        log.msg("endCall clearing %r"%(callcookie))
        self._currentCall = None
        if rtp:
            rtp = self._rtp[callcookie]
            rtp.stopSendingAndReceiving()
            del self._rtp[callcookie]
            if self._calls.get(callcookie):
                del self._calls[callcookie]
            self.closeAudioDevice()
        self.ui.callDisconnected(callcookie, reason)

    def openAudioDevice(self):
        if self._audio is None:
            audioPref = self.getPref('audio')
            audio_in = self.getPref('audio_infile')
            audio_out = self.getPref('audio_outfile')
            if audio_in and audio_out:
                aF = ( audio_in, audio_out )
            else:
                aF = None
            log.msg("Getting new audio device", system='phone')
            self._audio = getAudioDevice('rw', audioPref, aF)
            self._audio.close()
            log.msg("Got new audio device")

    def closeAudioDevice(self):
        self._audio.close()
        self._audioFormat = None
        #self._audio = None

    def receiveRTP(self, callcookie, payloadType, payloadData):
        if self._currentCall != callcookie:
            return None
        fmt = None
        if payloadType == 0:
            fmt = FMT_PCMU
        elif payloadType == 3:
            fmt = FMT_GSM
        if fmt:
            try:
                self._audio.write(payloadData, fmt)
            except IOError:
                pass
        elif payloadType in (13, 19):
            # comfort noise
            pass
        else:
            log.err("unexpected RTP PT %s len %d"%((payloadType,str(payloadType)), len(payloadData)))

    def giveRTP(self, callcookie):
        # Check that callcookie is the active call
        if self._currentCall != callcookie or self._muted:
            return None # comfort noise
        bytes = self._audio.read()
        if bytes is None:
            return None
        else:
            return self._audioFormat, bytes

    def placeCall(self, sipURL):
        return self.sip.placeCall(sipURL)

    def dropCall(self, cookie):
        call = self._calls.get(cookie)
        if call:
            d = call.dropCall()
        # xxx Add callback.
        #else:
        #    self.ui.callDisconnected(None, "no call")

    def startDTMF(self, cookie, digit):
        rtp = self._rtp[cookie]
        rtp.startDTMF(digit)

    def stopDTMF(self, cookie, digit):
        rtp = self._rtp[cookie]
        rtp.stopDTMF(digit)

    def statusMessage(self, message):
        self.ui.statusMessage(message)

    def debugMessage(self, message):
        self.ui.debugMessage(message)

    def appSpecificOptions(self, opts):
        app = OptionGroup('shtoom', 'Shtoom')
        app.addOption(ChoiceOption('ui','use UI for interface', choices=['qt','gnome','wx', 'tk','text']))
        app.addOption(ChoiceOption('audio','use AUDIO for interface', choices=['oss', 'fast', 'port']))
        app.addOption(StringOption('audio_infile','read audio from this file'))
        app.addOption(StringOption('audio_outfile','write audio to this file'))
        app.addOption(StringOption('ringing_command','run this command when a call comes in'))
        opts.addGroup(app)
        opts.setOptsFile('.shtoomrc')

    def authCred(self, method, uri, realm='unknown', retry=False):
        "Place holder for now"
        user = self.getPref('register_authuser')
        passwd = self.getPref('register_authpasswd')
        if user is not None and passwd is not None and retry is False:
            return defer.succeed((self.getPref('register_authuser'),
                                 self.getPref('register_authpasswd')))
        elif hasattr(self.ui, 'getAuth'):
            return self.ui.getAuth("Auth needed for %s %s, realm '%s'"%(method, uri, realm))
        else:
            return defer.fail(CallFailed("No auth available"))

    def muteCall(self, callcookie):
        if self._currentCall is not callcookie:
            raise ValueError, "call %s is current call, not %s"%(self._currentCall, callcookie)
        else:
            self._muted = True

    def unmuteCall(self, callcookie):
        if self._currentCall is not callcookie:
            raise ValueError, "call %s is current call, not %s"%(self._currentCall, callcookie)
        else:
            self._muted = False

    def switchCallAudio(self, callcookie):
        self._currentCall = callcookie

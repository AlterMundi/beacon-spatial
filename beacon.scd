// beacon.scd
// SuperCollider 3.13 + ATK (Ambisonic Toolkit) 13-band binaural spatializer
// for the Harmonic Beacon (40.4Hz guitar harmonic series + high harmonics).
//
// PlayBuf (looping harmonic_beacon_2026_05_13_session.wav, mono 48kHz)
//   -> 12x BPF (Q configurable) + 1x HPF (1818Hz) with per-band gain.lag(0.05)
//   -> per-band FoaPanB (az in radians, distance as 1/dist amp scaling)
//   -> sum B-format (WXYZ)
//   -> FoaDecode (Listen kernels, 48000/512) -> wet
//   -> dry = Mix(filter outputs * gains) * (1-mix)
//   -> (wet + dry) * master -> Out.ar(0,2)
// Nature WAV (mono duplicated to stereo, or stereo preserved)
//   -> looping \sample_player with bounded linear gain + release envelope
//   -> summed independently onto the same stereo output bus
//
// OSC (via OSCdef): /beacon/gain/N, /beacon/az/N, /beacon/dist/N (N=1..13),
//                   /beacon/q/N (N=1..12), /beacon/solo/N (N=1..13),
//                   /beacon/mix, /beacon/master,
//                   /beacon/nature/load, /beacon/nature/gain, /beacon/nature/stop
// The core 13-band DSP keeps lag(0.05) only on band gain and azimuth;
// the independent nature-layer gain also has a 50 ms safety lag.
// Server: 2in/2out, 48000Hz. NO LFOs, NO effects (no Proximity/NFC), NO reverb.
// ONLY FoaPanB + 1/dist scaling for spatialization.
//
// Usage:
//   ./start-beacon.sh [--osc-host HOST] [--osc-port PORT]
//   (or manually: pw-jack scsynth -u 57110 -i 2 -o 2 &
//                 BEACON_OSC_HOST=127.0.0.1 BEACON_OSC_PORT=57120 \
//                 QT_QPA_PLATFORM=offscreen sclang -u 57120 beacon.scd)
//
// Web UI (Flask) sends OSC /beacon/* to the configured sclang OSC port.
// OSCdefs call synth.set(...) which sends /n_set to scsynth:57110.
//
// Requires: ATK quark + kernels installed at ~/.local/share/ATK/kernels
//           sc3-plugins (for some ATK internals if needed, but core is in ATK)
//
// Band layout:
//   Bands 1-6:  40.4Hz series, 40.4Hz bandwidth [40.4, 80.8, 121.2, 161.6, 202, 242.4]
//   Bands 7-12: 242.4Hz series, 242.4Hz bandwidth [484.8, 727.2, 969.6, 1212, 1454.4, 1696.8]
//   Band 13:    HPF 1818Hz+ (no upper limit)

(
var buf, decoder, synth, oscdefs, helloRoutine, natureBuf, natureSynth;
var audioFilePath = "BEACON_AUDIO_FILE".getenv ? (PathName(thisProcess.nowExecutingPath).pathOnly +/+ "harmonic_beacon_2026_05_13_session.wav");
var useFile = "BEACON_SOURCE".getenv == "file";
var defName = if (useFile) { \beacon_file } { \beacon_live };
var contractId = "eaad56d9081d01c4a63646e0055b37b7";
var producerVersion = "1.0.0";
var streamId = 4.collect { 65536.rand.asHexString(4).toLower }.join;
var stateSeq = 0;
var oscListenHost = "BEACON_OSC_HOST".getenv ? "127.0.0.1";
var oscListenPort = ("BEACON_OSC_PORT".getenv ? "57120").asInteger;
// sclang opens UDP ports on all interfaces. Apply the configured bind rule at
// responder dispatch: loopback by default, or any source for 0.0.0.0 / "*".
var oscSourceFilter = if (["0.0.0.0", "*"].includes(oscListenHost)) {
  nil
} {
  NetAddr(oscListenHost, nil)
};

// Use pre-started scsynth (from start-beacon.sh) on standard port 57110.
// start-beacon.sh passes the configured sclang OSC port with -u.
var server = Server(\beacon, NetAddr("127.0.0.1", 57110));
Server.default = server;

// --- Server options (informational when scsynth started externally; applied only on boot) ---
server.options.numInputBusChannels = 2;
server.options.numOutputBusChannels = 2;
server.options.sampleRate = 48000;
server.options.memSize = 65536;   // headroom for kernels + buffers
server.options.blockSize = 64;    // default fine; kernel latency ~512/sr anyway

// --- Debug header ---
"".postln;
"========================================".postln;
"  BEACON SPATIALIZER (ATK FOA)          ".postln;
"  12 BPF + 1 HPF binaural (Listen HRTF)".postln;
"========================================".postln;
"SC: %  |  ATK kernels: %".format(Main.version, Atk.userKernelDir).postln;
if (useFile) {
  "MODE: FILE — %".format(audioFilePath.basename).postln;
} {
  "MODE: LIVE — SoundIn.ar(0) [R24 CH1]".postln;
};
"".postln;

// OSC: /beacon/* messages are received by sclang (OSCdef) on the configured port.
// They are translated to .set() calls on the running synth (which talks to scsynth on 57110).
"OSC listen rule: %:%".format(oscListenHost, oscListenPort).postln;
"scsynth (audio engine) on 57110 (external, started by start-beacon.sh).".postln;
"Launch via: ./start-beacon.sh [--live|--file] [--osc-host HOST] [--osc-port PORT]".postln;
"".postln;

// --- Attach to running scsynth (no boot attempt; script starts scsynth first) ---
server.startAliveThread(0.4);
server.doWhenBooted({
  // 12 BPF frequencies + HPF cutoff
  var bpfFreqs = [40.4, 80.8, 121.2, 161.6, 202, 242.4, 484.8, 727.2, 969.6, 1212, 1454.4, 1696.8, 1818];
  // RQ defaults: BW=40.4Hz for 1-6, BW=242.4Hz for 7-12
  var defaultRQs = [1.0, 0.5, 1.0/3, 0.25, 0.2, 1.0/6, 0.5, 1.0/3, 0.25, 0.2, 1.0/6, 1.0/7];
  var defaultGains = [1.2, 1.0, 1.0, 1.0, 1.0, 1.3, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0];
  var defaultAz    = [180, 135, -90, -45, 45, 0, 0, 0, 0, 0, 0, 0, 0];
  var defaultDist  = [2.0, 2.5, 3.0, 2.5, 2.0, 1.5, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0];
  var defaultSolo  = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
  var mix0 = 0.85, master0 = 0.9;
  var cond = Condition.new;
  var readableControls = [];
  var natureGain = 0.0, naturePath = "", natureLoadGeneration = 0;
  var knownClients = List.new;
  var stateDumpQueue = List.new;
  var stateDumpBusy = false;
  var setControl, rememberClient, sendHello, sendNextStateDump;
  var releaseNature, loadNature;
  var makeBeaconDef = { |name, srcFunc|
    SynthDef(name, {
      arg out = 0, bufnum = 0;

      // NamedControls with .lag(0.05) ONLY on azimuth/gain (per spec)
      var gains = defaultGains.collect { |val, i|
        ("gain" ++ (i + 1)).asSymbol.kr(val).lag(0.05)
      };
      var azs = defaultAz.collect { |val, i|
        ("az" ++ (i + 1)).asSymbol.kr(val).lag(0.05)
      };
      var dists = defaultDist.collect { |val, i|
        ("dist" ++ (i + 1)).asSymbol.kr(val)
      };
      var solos = defaultSolo.collect { |val, i|
        ("solo" ++ (i + 1)).asSymbol.kr(val)
      };
      var mix    = \mix.kr(mix0);
      var master = \master.kr(master0);

      // Source injected by factory function (file or live)
      var src = srcFunc.value(bufnum);

      var qCtrls = 12.collect { |i|
        ("q" ++ (i + 1)).asSymbol.kr(defaultRQs[i]).lag(0.05)
      };

      // 12x BPF (Q configurable) + 1x HPF (1818Hz, no upper limit)
      var bpfs = bpfFreqs.collect { |freq, i|
        var sig;
        if (i == 12) {
          sig = HPF.ar(src, freq);
        } {
          sig = BPF.ar(src, freq, qCtrls[i]);
        };
        sig * gains[i]
      };

      // Solo logic: if any solo is active, only soloed bands pass
      var anySolo = solos.sum;
      var gates = solos.collect { |s| (anySolo <= 0) + (s * (anySolo > 0)) };
      var gatedBpfs = bpfs.collect { |bpfSig, i| bpfSig * gates[i] };

      // Dry path: Mix(gated filter outputs) * (1-mix)
      var drySig = Mix(gatedBpfs) * (1 - mix);

      // Wet path: per-band FoaPanB(az in rad, distance via 1/dist scaling)
      // Distance scaling applied pre-encode (affects B-format contribution level)
      var foas = gatedBpfs.collect { |bpfSig, i|
        var azRad = azs[i].degrad;
        var d = dists[i].max(0.1);   // avoid div0 / extreme boost at dist=0
        FoaPanB.ar(bpfSig / d, azRad, 0)
      };

      // Sum to single B-format (4 channels: W X Y Z)
      var bfmt = Mix(foas);

      // Decode B-format -> binaural stereo via Listen HRTF kernels
      var wetSig = FoaDecode.ar(bfmt, decoder) * mix;

      // Final wet/dry mix + master
      var sig = (wetSig + drySig) * master;

      Out.ar(out, sig);   // 2 channels
    }).add;
  };

  "Server booted (2in/2out @ 48000Hz).".postln;
  server.freeAll;   // clean any prior nodes on re-run

  if (useFile) {
    // Load source buffer (looping WAV)
    "Loading buffer: % ...".format(audioFilePath.basename).postln;
    buf = Buffer.read(server, audioFilePath, action: {
      "  Buffer ready: bufnum=%, % frames, %s".format(
        buf.bufnum, buf.numFrames, buf.duration.round(0.01)
      ).postln;
      cond.unhang;
    });
    cond.hang;
  };

  // Load decoder kernel (Listen subject 1002, explicit 48000/512 path inside ATK)
  "Loading FoaDecoderKernel.newListen(1002, 48000Hz, 512-sample kernels)...".postln;
  decoder = FoaDecoderKernel.newListen(1002, server, 48000);
  // Kernels load async (see 'Kernel HRIR_*.wav, channel * loaded.' posts above)
  2.0.wait;
  "  Decoder kernel ready (allow ~11ms latency from 512-sample HRIR).".postln;

  // Define the core SynthDef
  "Defining SynthDef \\% ...".format(defName).postln;
  if (useFile) {
    makeBeaconDef.value(defName, { |bufnum|
      PlayBuf.ar(1, bufnum, BufRateScale.kr(bufnum), loop: 1)
    });
  } {
    makeBeaconDef.value(defName, { |bufnum| SoundIn.ar(0) });
  };

  // Nature buffers are always loaded as two channels: mono WAVs duplicate
  // channel 0 and stereo WAVs preserve channels 0/1. This keeps PlayBuf's
  // compile-time channel count correct for both supported source formats.
  SynthDef(\sample_player, {
    arg out = 0, bufnum = 0, gain = 0.0, gate = 1, release = 0.1;
    var sig = PlayBuf.ar(2, bufnum, BufRateScale.kr(bufnum), loop: 1);
    var envelope = EnvGen.kr(
      Env.asr(0.01, 1.0, release.max(0.01)),
      gate,
      doneAction: Done.freeSelf
    );
    Out.ar(out, sig * gain.clip(0.0, 1.0).lag(0.05) * envelope);
  }).add;

  server.sync;
  "SynthDefs \\% and \\sample_player added.".format(defName).postln;

  // Instantiate
  if (useFile) {
    synth = Synth(defName, [\bufnum, buf.bufnum]);
  } {
    synth = Synth(defName);
  };
  "Synth active: nodeID=%  (headphones required for binaural)".format(synth.nodeID).postln;

  releaseNature = { |node|
    if (node.notNil) { node.set(\gate, 0) };
  };

  loadNature = { |rawPath|
    var path = rawPath.standardizePath;
    var pathName = PathName(path);
    var soundFile, sourceChannels, sourceFrames, loadGeneration;
    var valid = true;

    if (PathName(rawPath).isAbsolutePath.not) {
      "[NATURE] Rejected non-absolute local path: %".format(rawPath).warn;
      valid = false;
    };
    if (valid and: { pathName.extension.toLower != "wav" }) {
      "[NATURE] Rejected non-WAV path: %".format(path).warn;
      valid = false;
    };
    if (valid and: { File.exists(path).not }) {
      "[NATURE] Rejected missing or unreadable path: %".format(path).warn;
      valid = false;
    };

    if (valid) {
      soundFile = SoundFile.new;
      if (soundFile.openRead(path)) {
        sourceChannels = soundFile.numChannels;
        sourceFrames = soundFile.numFrames;
        soundFile.close;
        if ([1, 2].includes(sourceChannels).not) {
          "[NATURE] Rejected WAV with % channels (only mono/stereo supported): %"
            .format(sourceChannels, path).warn;
          valid = false;
        };
        if (sourceFrames <= 0) {
          "[NATURE] Rejected empty WAV: %".format(path).warn;
          valid = false;
        };
      } {
        "[NATURE] Rejected invalid or unreadable WAV: %".format(path).warn;
        valid = false;
      };
    };

    if (valid) {
      natureLoadGeneration = natureLoadGeneration + 1;
      loadGeneration = natureLoadGeneration;
      "[NATURE] Loading: %".format(path).postln;
      Buffer.readChannel(
        server,
        path,
        channels: if (sourceChannels == 1) { [0, 0] } { [0, 1] },
        action: { |newBuf|
          var oldSynth, newSynth;
          if (loadGeneration != natureLoadGeneration) {
            newBuf.free;
            "[NATURE] Discarded superseded load: %".format(path).postln;
          } {
            oldSynth = natureSynth;
            newSynth = Synth.after(
              synth,
              \sample_player,
              [\bufnum, newBuf.bufnum, \gain, natureGain]
            );
            newSynth.onFree {
              newBuf.free;
              if (natureSynth === newSynth) {
                natureSynth = nil;
                natureBuf = nil;
                naturePath = "";
                stateSeq = stateSeq + 1;
              };
            };
            natureBuf = newBuf;
            natureSynth = newSynth;
            naturePath = path;
            stateSeq = stateSeq + 1;
            releaseNature.value(oldSynth);
            "[NATURE] Active: % (source channels=%, buffer channels=%)"
              .format(path, sourceChannels, newBuf.numChannels).postln;
          };
        }
      );
    };
  };

  // The synth's NamedControls remain the only mutable parameter state. The
  // language queries them for dumps instead of maintaining a duplicate model.
  // Nature load/gain are language-owned because they remain readable even when
  // no sample synth exists.
  13.do { |i|
    var n = i + 1;
    readableControls = readableControls.add([("gain" ++ n).asSymbol, "/beacon/gain/" ++ n]);
    readableControls = readableControls.add([("az" ++ n).asSymbol, "/beacon/az/" ++ n]);
    readableControls = readableControls.add([("dist" ++ n).asSymbol, "/beacon/dist/" ++ n]);
    readableControls = readableControls.add([("solo" ++ n).asSymbol, "/beacon/solo/" ++ n]);
    if (i < 12) {
      readableControls = readableControls.add([("q" ++ n).asSymbol, "/beacon/q/" ++ n]);
    };
  };
  readableControls = readableControls.add([\mix, "/beacon/mix"]);
  readableControls = readableControls.add([\master, "/beacon/master"]);

  setControl = { |name, value|
    synth.set(name, value);
    stateSeq = stateSeq + 1;
  };

  rememberClient = { |addr|
    var known = knownClients.detect { |client|
      (client.addr == addr.addr) and: { client.port == addr.port }
    };
    if (known.isNil) { knownClients.add(addr) };
  };

  sendHello = { |addr|
    addr.sendMsg(
      "/beacon/hello",
      "beacon-spatial",
      streamId,
      "1.0.0",
      producerVersion,
      contractId,
      stateSeq
    );
  };

  // Serialize dump queries so one /n_set reply maps to exactly one requester.
  // Each query reads all 66 core NamedControls from scsynth in one response,
  // appends the two language-owned nature fields, and emits begin, values, and
  // end as members of one atomic OSC bundle.
  sendNextStateDump = {
    var request, recipient, dumpSeq;
    if (stateDumpQueue.isEmpty) {
      stateDumpBusy = false;
    } {
      stateDumpBusy = true;
      request = stateDumpQueue.removeAt(0);
      recipient = request[0];
      dumpSeq = request[1];
      OSCFunc({ |reply|
        var values = IdentityDictionary.new;
        var bundle = [["/beacon/state/begin", streamId, dumpSeq, contractId]];
        reply[2..].clump(2).do { |pair|
          values.put(pair[0].asSymbol, pair[1].asFloat);
        };
        readableControls.do { |spec|
          bundle = bundle.add([spec[1], values[spec[0]]]);
        };
        bundle = bundle.add(["/beacon/nature/load", naturePath]);
        bundle = bundle.add(["/beacon/nature/gain", natureGain]);
        bundle = bundle.add(["/beacon/state/end", streamId, dumpSeq]);
        recipient.sendBundle(0.0, *bundle);
        stateDumpBusy = false;
        sendNextStateDump.value;
      }, '/n_set', server.addr, argTemplate: [synth.nodeID]).oneShot;
      server.sendMsg(\s_get, synth.nodeID, *readableControls.collect { |spec| spec[0] });
    };
  };

  // OSCdefs: the 72 native addresses plus hello-request and state-request.
  oscdefs = [];
  13.do { |i|
    var n = i + 1;
    oscdefs = oscdefs.add(
      OSCdef(
        ("beacon_gain_" ++ n).asSymbol,
        { |msg| setControl.value(("gain" ++ n).asSymbol, msg[1].asFloat) },
        "/beacon/gain/" ++ n,
        oscSourceFilter,
        oscListenPort
      )
    );
    oscdefs = oscdefs.add(
      OSCdef(
        ("beacon_az_" ++ n).asSymbol,
        { |msg| setControl.value(("az" ++ n).asSymbol, msg[1].asFloat) },
        "/beacon/az/" ++ n,
        oscSourceFilter,
        oscListenPort
      )
    );
    oscdefs = oscdefs.add(
      OSCdef(
        ("beacon_dist_" ++ n).asSymbol,
        { |msg| setControl.value(("dist" ++ n).asSymbol, msg[1].asFloat) },
        "/beacon/dist/" ++ n,
        oscSourceFilter,
        oscListenPort
      )
    );
    if (i < 12) {
      oscdefs = oscdefs.add(
        OSCdef(
          ("beacon_q_" ++ n).asSymbol,
          { |msg|
            if (msg[1].isNumber and: { msg[1] >= 0.01 } and: { msg[1] <= 2 }) {
              setControl.value(("q" ++ n).asSymbol, msg[1].asFloat)
            }
          },
          "/beacon/q/" ++ n,
          oscSourceFilter,
          oscListenPort
        )
      );
    };
    oscdefs = oscdefs.add(
      OSCdef(
        ("beacon_solo_" ++ n).asSymbol,
        { |msg| setControl.value(("solo" ++ n).asSymbol, msg[1].asFloat) },
        "/beacon/solo/" ++ n,
        oscSourceFilter,
        oscListenPort
      )
    );
  };
  oscdefs = oscdefs.add(
    OSCdef(
      \beacon_mix,
      { |msg| setControl.value(\mix, msg[1].asFloat) },
      '/beacon/mix',
      oscSourceFilter,
      oscListenPort
    )
  );
  oscdefs = oscdefs.add(
    OSCdef(
      \beacon_master,
      { |msg| setControl.value(\master, msg[1].asFloat) },
      '/beacon/master',
      oscSourceFilter,
      oscListenPort
    )
  );

  // Nature sample layer. Loading is restricted to readable, absolute local
  // mono/stereo WAV paths. A valid replacement is swapped in only after its
  // stereo buffer is ready; superseded asynchronous loads free themselves.
  oscdefs = oscdefs.add(
    OSCdef(\beacon_nature_load, { |msg|
      // sclang decodes a standard OSC `s` argument as Symbol, while direct
      // language calls may still supply String. Coerce only those two textual
      // types so numeric/blob payloads cannot become path strings implicitly.
      if ((msg.size > 1) and: {
        msg[1].isKindOf(String) or: { msg[1].isKindOf(Symbol) }
      }) {
        "[NATURE] Accepted OSC load argument type: %."
          .format(msg[1].class).postln;
        loadNature.value(msg[1].asString);
      } {
        "[NATURE] Rejected load without one OSC string path.".warn;
      };
    }, '/beacon/nature/load', oscSourceFilter, oscListenPort)
  );
  oscdefs = oscdefs.add(
    OSCdef(\beacon_nature_gain, { |msg|
      var requestedGain;
      if ((msg.size > 1) and: { msg[1].isNumber }) {
        requestedGain = msg[1].asFloat;
        if (requestedGain.isNaN or: { requestedGain.abs > 1e12 }) {
          "[NATURE] Rejected non-finite gain.".warn;
        } {
          natureGain = requestedGain.clip(0.0, 1.0);
          if (natureSynth.notNil) { natureSynth.set(\gain, natureGain) };
          stateSeq = stateSeq + 1;
        };
      } {
        "[NATURE] Rejected gain without one numeric OSC argument.".warn;
      };
    }, '/beacon/nature/gain', oscSourceFilter, oscListenPort)
  );
  oscdefs = oscdefs.add(
    OSCdef(\beacon_nature_stop, { |msg|
      var oldSynth = natureSynth;
      natureLoadGeneration = natureLoadGeneration + 1;
      natureSynth = nil;
      natureBuf = nil;
      naturePath = "";
      stateSeq = stateSeq + 1;
      releaseNature.value(oldSynth);
      "[NATURE] Stopped.".postln;
    }, '/beacon/nature/stop', oscSourceFilter, oscListenPort)
  );

  // Recording control
  oscdefs = oscdefs.add(
    OSCdef(\beacon_record_start, { |msg|
      var path = msg[1].asString;
      if(path == "", {
        path = "/home/nicolas/Music/beacon/beacon_record_%.wav".format(Date.localtime.stamp);
      });
      server.record(path: path, numChannels: 2);
      stateSeq = stateSeq + 1;
      "[RECORD] Started: %".format(path).postln;
    }, '/beacon/record/start', oscSourceFilter, oscListenPort)
  );
  oscdefs = oscdefs.add(
    OSCdef(\beacon_record_stop, { |msg|
      server.stopRecording;
      stateSeq = stateSeq + 1;
      "[RECORD] Stopped.".postln;
    }, '/beacon/record/stop', oscSourceFilter, oscListenPort)
  );

  // Reset control
  oscdefs = oscdefs.add(
    OSCdef(\beacon_reset, { |msg|
      13.do { |i|
        var n = i + 1;
        setControl.value(("gain" ++ n).asSymbol, defaultGains[i]);
        setControl.value(("az" ++ n).asSymbol, defaultAz[i]);
        setControl.value(("dist" ++ n).asSymbol, defaultDist[i]);
        setControl.value(("solo" ++ n).asSymbol, 0);
        if (i < 12) {
          setControl.value(("q" ++ n).asSymbol, defaultRQs[i]);
        };
      };
      setControl.value(\mix, mix0);
      setControl.value(\master, master0);
      "[RESET] All parameters restored to defaults.".postln;
    }, '/beacon/reset', oscSourceFilter, oscListenPort)
  );

  // Contract handshake and on-connect state synchronization.
  oscdefs = oscdefs.add(
    OSCdef(\beacon_hello_request, { |msg, time, addr|
      rememberClient.value(addr);
      sendHello.value(addr);
    }, '/beacon/hello/request', oscSourceFilter, oscListenPort)
  );
  oscdefs = oscdefs.add(
    OSCdef(\beacon_state_request, { |msg, time, addr|
      var expectedContractId = if (msg.size > 1) { msg[1].asString } { "" };
      rememberClient.value(addr);
      if (expectedContractId == contractId) {
        stateSeq = stateSeq + 1;
        stateDumpQueue.add([addr, stateSeq]);
        if (stateDumpBusy.not) { sendNextStateDump.value };
      } {
        "[STATE] Ignored dump request with missing or mismatched contract_id from %.".format(addr).warn;
        sendHello.value(addr);
      };
    }, '/beacon/state', oscSourceFilter, oscListenPort)
  );

  helloRoutine = Routine({
    loop {
      1.0.wait;
      knownClients.do { |client| sendHello.value(client) };
    }
  }).play(AppClock);

  "OSCdefs registered: 72 native addresses + hello request + state request (74 total).".postln;

  // Cleanup hooks
  ServerQuit.add({
    "ServerQuit: freeing beacon resources...".postln;
    if (helloRoutine.notNil) { helloRoutine.stop };
    oscdefs.do { |d| d.free };
    natureLoadGeneration = natureLoadGeneration + 1;
    if (natureSynth.notNil) { natureSynth.free };
    if (natureBuf.notNil) { natureBuf.free };
    if (synth.notNil) { synth.free };
    if (decoder.notNil) { decoder.free; "  decoder kernel buffers freed".postln; };
    if (buf.notNil) { buf.free; "  audio buffer freed".postln; };
  }, server);

  CmdPeriod.add({
    "Cmd-. : audio stopped (node freed). Kernel decoder + buffer remain allocated.".postln;
    "        Full cleanup: decoder.free; buf.free;".postln;
  });

  // Final ready banner + defaults
  "".postln;
  "========================================".postln;
  "  BEACON READY                          ".postln;
  "  OSC %:% | scsynth 127.0.0.1:57110".format(oscListenHost, oscListenPort).postln;
  "========================================".postln;
  "Bands 1-6 : [ 40.4, 80.8, 121.2, 161.6, 202, 242.4 ] Hz (40.4Hz BW)".postln;
  "Bands 7-12: [ 484.8, 727.2, 969.6, 1212, 1454.4, 1696.8 ] Hz (242.4Hz BW)".postln;
  "Band 13   : HPF 1818Hz+".postln;
  "Initial gains: %   (0-3)".format(defaultGains).postln;
  "Initial az:    % deg (-180..180)".format(defaultAz).postln;
  "Initial dist:  %   (0-10)".format(defaultDist).postln;
  "mix=%, master=%".format(mix0, master0).postln;
  "".postln;
  if (useFile) {
    "Signal: PlayBuf -> BPF*12 + HPF*1 -> FoaPanB(az.rad, 1/dist) -> B-format".postln;
  } {
    "Signal: SoundIn.ar(0) [R24 CH1] -> BPF*12 + HPF*1 -> FoaPanB(az.rad, 1/dist) -> B-format".postln;
  };
  "        -> FoaDecode(Listen) = wet   |   Mix(filters*gains) * (1-mix)".postln;
  "        -> (wet + dry) * master -> stereo out".postln;
  "".postln;
"No LFOs, no reverb, no extra effects (plain FoaPanB + 1/dist only).".postln;
"To stop: ctrl-. (or s.quit; decoder.free; buf.free; 0.exit; )".postln;
"".postln;

// Keep sclang alive (OSCdefs remain active)
"sclang waiting for OSC...".postln;
});
)

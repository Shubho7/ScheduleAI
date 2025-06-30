export async function startAudioPlayerWorklet() {
    // Create an AudioContext
    const audioContext = new AudioContext({
      sampleRate: 24000,
    });
  
    const workletURL = new URL("./pcm-player-processor.js", import.meta.url);
    await audioContext.audioWorklet.addModule(workletURL);
  
    // Create an AudioWorkletNode
    const audioPlayerNode = new AudioWorkletNode(
      audioContext,
      "pcm-player-processor"
    );
  
    audioPlayerNode.connect(audioContext.destination);
    return [audioPlayerNode, audioContext];
  }
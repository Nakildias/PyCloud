// static/js/gba_audio_processor.js
class GBAAudioProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super(options);
        this.buffer = []; // CORRECTED LINE
        this.port.onmessage = (event) => {
            if (event.data.type === 'AUDIO_DATA' && event.data.samples) {
                for (let i = 0; i < event.data.samples.length; i++) {
                    this.buffer.push(event.data.samples[i]);
                }
            }
        };
    }

    process(inputs, outputs, parameters) {
        const outputChannels = outputs[0]; // outputs is an array of output connections
        // each output connection is an array of channels (Float32Array)

        if (!outputChannels || outputChannels.length < 2) {
            // Not enough channels to output stereo, or output is not connected
            return true; // Keep processor alive
        }

        const outputChannelLeft = outputChannels[0];
        const outputChannelRight = outputChannels[1];

        if (!outputChannelLeft || !outputChannelRight) return true; // Should not happen if length check passed

        for (let i = 0; i < outputChannelLeft.length; i++) {
            if (this.buffer.length >= 2) {
                outputChannelLeft[i] = this.buffer.shift();  // Left sample
                outputChannelRight[i] = this.buffer.shift(); // Right sample
            } else {
                outputChannelLeft[i] = 0; // Silence if buffer is empty
                outputChannelRight[i] = 0;
            }
        }
        return true; // Keep processor alive
    }
}

registerProcessor('gba-audio-processor', GBAAudioProcessor);

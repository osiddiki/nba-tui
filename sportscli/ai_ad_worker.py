"""Separate optional runtime: classify local mpv frames, never download or transmit them."""
import json
import sys


def main():
    try:
        import numpy as np
        from PIL import Image
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            import tensorflow as tf
            Interpreter = tf.lite.Interpreter
        interpreter = Interpreter(model_path=sys.argv[1], num_threads=2)
        interpreter.allocate_tensors()
        source, target = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
        # Models declare their own frame size; quantized models take integer pixels.
        height, width = int(source['shape'][1]), int(source['shape'][2])
        in_scale, in_zero = source.get('quantization', (0.0, 0))
        out_scale, out_zero = target.get('quantization', (0.0, 0))
        print(json.dumps({'ready': True}), flush=True)
        for line in sys.stdin:
            try:
                path = json.loads(line)['image']
                with Image.open(path) as image:
                    pixels = np.asarray(image.convert('RGB').resize((width, height)), dtype='float32')[None]
                if source['dtype'] != np.float32:
                    info = np.iinfo(source['dtype'])
                    pixels = np.clip(np.round(pixels / in_scale + in_zero), info.min, info.max) if in_scale else pixels
                    pixels = pixels.astype(source['dtype'])
                interpreter.set_tensor(source['index'], pixels)
                interpreter.invoke()
                raw = interpreter.get_tensor(target['index']).reshape(-1)[0]
                score = float((float(raw) - out_zero) * out_scale) if target['dtype'] != np.float32 and out_scale else float(raw)
                print(json.dumps({'score':score}), flush=True)
            except (OSError, ValueError, KeyError, TypeError):
                print(json.dumps({'error':'frame could not be classified'}), flush=True)
    except (ImportError, OSError, ValueError, IndexError):
        print(json.dumps({'ready': False}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

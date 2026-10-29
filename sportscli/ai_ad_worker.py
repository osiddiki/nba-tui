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
        input_id = interpreter.get_input_details()[0]['index']
        output_id = interpreter.get_output_details()[0]['index']
        print(json.dumps({'ready': True}), flush=True)
        for line in sys.stdin:
            try:
                path = json.loads(line)['image']
                with Image.open(path) as image:
                    pixels = np.asarray(image.convert('RGB').resize((320, 200)), dtype='float32')[None]
                interpreter.set_tensor(input_id, pixels)
                interpreter.invoke()
                score = float(interpreter.get_tensor(output_id)[0][0])
                print(json.dumps({'score':score}), flush=True)
            except (OSError, ValueError, KeyError, TypeError):
                print(json.dumps({'error':'frame could not be classified'}), flush=True)
    except (ImportError, OSError, ValueError, IndexError):
        print(json.dumps({'ready': False}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

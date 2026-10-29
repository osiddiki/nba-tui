"""Developer-only: quantize the upstream NBA classifier for the optional release."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Upstream part5_cropped_5-29-24.keras file')
    parser.add_argument('output', help='Destination .tflite file')
    args = parser.parse_args()
    import tensorflow as tf
    model = tf.keras.models.load_model(args.source, compile=False)

    @tf.function(input_signature=[tf.TensorSpec([1, 200, 320, 3], tf.float32, name='image')])
    def predict(image):
        return {'score':model(image, training=False)}

    converter = tf.lite.TFLiteConverter.from_concrete_functions([predict.get_concrete_function()], model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    data = converter.convert()
    Path(args.output).write_bytes(data)
    print(f'Wrote {len(data)} bytes to {args.output}')


if __name__ == '__main__':
    main()

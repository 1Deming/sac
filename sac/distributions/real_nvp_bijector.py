"""RealNVP bijector."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
ConditionalBijector = tf.contrib.distributions.bijectors.ConditionalBijector

__all__ = [
    "RealNVPBijector",
]


def checkerboard(shape, parity="even", dtype=tf.bool):
    """TODO: Check this implementation"""
    unit = (tf.constant((True, False))
            if parity == "even" else tf.constant((False, True)))

    tiled = tf.tile(unit, (np.prod(shape) // 2, ))
    return tf.cast(tf.reshape(tiled, shape), dtype)


def feedforward_net(inputs,
                    layer_sizes,
                    activation_fn=tf.nn.tanh,
                    output_nonlinearity=None,
                    regularizer=None):
    prev_size = inputs.get_shape().as_list()[-1]
    out = inputs
    for i, layer_size in enumerate(layer_sizes):
        weight_initializer = tf.contrib.layers.xavier_initializer()
        weight = tf.get_variable(
            name="weight_{i}".format(i=i),
            shape=(prev_size, layer_size),
            initializer=weight_initializer,
            regularizer=regularizer)

        bias_initializer = tf.initializers.random_normal()
        bias = tf.get_variable(
            name="bias_{i}".format(i=i),
            shape=(layer_size, ),
            initializer=bias_initializer)

        prev_size = layer_size
        z = tf.matmul(out, weight) + bias

        if i < len(layer_sizes) - 1 and activation_fn is not None:
            out = activation_fn(z)
        elif i == len(layer_sizes) - 1 and output_nonlinearity is not None:
            out = output_nonlinearity(z)
        else:
            out = z

    return out

class CouplingBijector(ConditionalBijector):
    """TODO"""

    def __init__(self,
                 parity,
                 translation_fn,
                 scale_fn,
                 event_ndims=0,
                 validate_args=False,
                 name="coupling_bijector"):
        """Instantiates the `CouplingBijector` bijector.

        Args:
            TODO
            event_ndims: Python scalar indicating the number of dimensions associated
                with a particular draw from the distribution.
            validate_args: Python `bool` indicating whether arguments should be
                checked for correctness.
            name: Python `str` name given to ops managed by this object.

        Raises:
            ValueError: if TODO happens
        """
        self._graph_parents = []
        self._name = name
        self._validate_args = validate_args

        self.parity = parity
        self.translation_fn = translation_fn
        self.scale_fn = scale_fn

        super().__init__(event_ndims=event_ndims,
                         validate_args=validate_args,
                         name=name)

    # TODO: Properties

    def get_mask(self, x, dtype):
        shape = x.get_shape()
        mask = checkerboard(shape[1:], parity=self.parity, dtype=dtype)

        # TODO: remove assert
        assert mask.get_shape() == shape[1:]

        return mask

    def _forward(self, x, **condition_kwargs):
        self._maybe_assert_valid_x(x)

        mask = self.get_mask(x, dtype=x.dtype)

        # masked half of the x
        masked_x = x * mask

        # TODO: scale and translation could be merged into a single network
        with tf.variable_scope("{name}/scale".format(name=self.name),
                               reuse=tf.AUTO_REUSE):
            scale = mask * self.scale_fn(masked_x, **condition_kwargs)

        with tf.variable_scope("{name}/translation".format(name=self.name),
                               reuse=tf.AUTO_REUSE):
            translation = mask * self.translation_fn(
                masked_x, **condition_kwargs)

        exp_scale = tf.check_numerics(
            tf.exp(scale), "tf.exp(scale) contains NaNs or Infs.")
        # (9) in paper

        if self.parity == "odd":
            out = tf.stack((
                x[:, 0] * exp_scale[:, 1] + translation[:, 1],
                x[:, 1],
            ), axis=1)
        else:
            out = tf.stack((
                x[:, 0],
                x[:, 1] * exp_scale[:, 0] + translation[:, 0],
            ), axis=1)

        return out

    def _forward_log_det_jacobian(self, x, **condition_kwargs):
        self._maybe_assert_valid_x(x)

        mask = self.get_mask(x, dtype=x.dtype)

        # masked half of the x
        masked_x = x * mask

        # TODO: scale and translation could be merged into a single network
        with tf.variable_scope("{name}/scale".format(name=self.name),
                               reuse=tf.AUTO_REUSE):
            scale = mask * self.scale_fn(masked_x, **condition_kwargs)

        log_det_jacobian = tf.reduce_sum(
            scale, axis=tuple(range(1, len(x.shape))))

        return log_det_jacobian

    def _inverse(self, y, **condition_kwargs):
        self._maybe_assert_valid_y(y)

        mask = self.get_mask(y, dtype=y.dtype)

        masked_y = y * mask

        # TODO: scale and translation could be merged into a single network
        with tf.variable_scope("{name}/scale".format(name=self.name),
                               reuse=tf.AUTO_REUSE):
            scale = mask * self.scale_fn(masked_y, **condition_kwargs)

        with tf.variable_scope("{name}/translation".format(name=self.name),
                               reuse=tf.AUTO_REUSE):
            translation = mask * self.translation_fn(
                masked_y, **condition_kwargs)

        if self.parity == "odd":
            out = tf.stack((
                (y[:, 0] - translation[:, 1]) * tf.exp(-scale[:, 1]),
                y[:, 1],
            ), axis=1)
        else:
            out = tf.stack((
                y[:, 0],
                (y[:, 1] - translation[:, 0]) * tf.exp(-scale[:, 0]),
            ), axis=1)

        return out


    def _inverse_log_det_jacobian(self, y, **condition_kwargs):
        self._maybe_assert_valid_y(y)

        mask = self.get_mask(y, dtype=y.dtype)

        # masked half of the y
        masked_y = y * mask

        # TODO: scale and translation could be merged into a single network
        with tf.variable_scope("{name}/scale".format(name=self.name),
                               reuse=tf.AUTO_REUSE):
            scale = mask * self.scale_fn(masked_y, **condition_kwargs)

        log_det_jacobian = -tf.reduce_sum(
            scale, axis=tuple(range(1, len(y.shape))))

        return log_det_jacobian

    def _maybe_assert_valid_x(self, x):
        """TODO"""
        if not self.validate_args:
            return x
        raise NotImplementedError("_maybe_assert_valid_x")

    def _maybe_assert_valid_y(self, y):
        """TODO"""
        if not self.validate_args:
            return y
        raise NotImplementedError("_maybe_assert_valid_y")


DEFAULT_CONFIG = {
    "num_coupling_layers": 2,
    "translation_hidden_sizes": (25, ),
    "scale_hidden_sizes": (25, ),
    "scale_regularization": 5e2
}

class RealNVPBijector(ConditionalBijector):
    """TODO"""

    def __init__(self,
                 config=None,
                 event_ndims=0,
                 validate_args=False,
                 name="real_nvp"):
        """Instantiates the `RealNVPBijector` bijector.

        Args:
            TODO
            event_ndims: Python scalar indicating the number of dimensions associated
                with a particular draw from the distribution.
            validate_args: Python `bool` indicating whether arguments should be
                checked for correctness.
            name: Python `str` name given to ops managed by this object.

        Raises:
            ValueError: if TODO happens
        """
        self._graph_parents = []
        self._name = name
        self._validate_args = validate_args

        self.config = dict(DEFAULT_CONFIG, **(config or {}))

        self.build()

        super().__init__(event_ndims=event_ndims,
                         validate_args=validate_args,
                         name=name)

    # TODO: Properties

    def build(self):
        num_coupling_layers = self.config["num_coupling_layers"]
        translation_hidden_sizes = self.config["translation_hidden_sizes"]
        scale_hidden_sizes = self.config["scale_hidden_sizes"]

        def translation_wrapper(inputs, observations):
            return feedforward_net(
                tf.concat((inputs, observations), axis=1),
                # TODO: should allow multi_dimensional inputs/outputs
                layer_sizes=(*translation_hidden_sizes, inputs.shape.as_list()[-1]))

        def scale_wrapper(inputs, observations):
            return feedforward_net(
                tf.concat((inputs, observations), axis=1),
                # TODO: should allow multi_dimensional inputs/outputs
                layer_sizes=(*scale_hidden_sizes, inputs.shape.as_list()[-1]),
                regularizer=tf.contrib.layers.l2_regularizer(
                    self.config["scale_regularization"]))

        self.layers = [
            CouplingBijector(
                parity=("even", "odd")[i % 2],
                name="coupling_{i}".format(i=i),
                translation_fn=translation_wrapper,
                scale_fn=scale_wrapper)
            for i in range(1, num_coupling_layers + 1)
        ]

    def _forward(self, x, **condition_kwargs):
        self._maybe_assert_valid_x(x)

        out = x
        for layer in self.layers:
            out = layer.forward(out, **condition_kwargs)

        return out

    def _forward_log_det_jacobian(self, x, **condition_kwargs):
        self._maybe_assert_valid_x(x)

        sum_log_det_jacobians = tf.reduce_sum(
            tf.zeros_like(x), axis=tuple(range(1, len(x.shape))))

        out = x
        for layer in self.layers:
            log_det_jacobian = layer.forward_log_det_jacobian(
                out, **condition_kwargs)
            out = layer.forward(out, **condition_kwargs)
            assert (sum_log_det_jacobians.shape.as_list()
                    == log_det_jacobian.shape.as_list())

            sum_log_det_jacobians += log_det_jacobian

        return sum_log_det_jacobians

    def _inverse(self, y, **condition_kwargs):
        self._maybe_assert_valid_y(y)

        out = y
        for layer in reversed(self.layers):
            out = layer.inverse(out, **condition_kwargs)

        return out

    def _inverse_log_det_jacobian(self, y, **condition_kwargs):
        self._maybe_assert_valid_y(y)

        sum_log_det_jacobians = tf.reduce_sum(
            tf.zeros_like(y), axis=tuple(range(1, len(y.shape))))

        out = y
        for layer in reversed(self.layers):
            log_det_jacobian = layer.inverse_log_det_jacobian(
                out, **condition_kwargs)
            out = layer.inverse(out, **condition_kwargs)
            assert (sum_log_det_jacobians.shape.as_list()
                    == log_det_jacobian.shape.as_list())

            sum_log_det_jacobians += log_det_jacobian

        return sum_log_det_jacobians

    def _maybe_assert_valid_x(self, x):
        """TODO"""
        if not self.validate_args:
            return x
        raise NotImplementedError("_maybe_assert_valid_x")

    def _maybe_assert_valid_y(self, y):
        """TODO"""
        if not self.validate_args:
            return y
        raise NotImplementedError("_maybe_assert_valid_y")

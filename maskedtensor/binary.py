# Copyright (c) Meta Platforms, Inc. and affiliates

import torch

BINARY_NAMES = [
    "add",
    #    "addcdiv",
    #    "addcmul",
    "atan2",
    "arctan2",
    "bitwise_and",
    "bitwise_or",
    "bitwise_xor",
    "bitwise_left_shift",
    "bitwise_right_shift",
    "div",
    "divide",
    "floor_divide",
    "fmod",
    "logaddexp",
    "logaddexp2",
    #    "logical_and",
    #    "logical_or",
    #    "logical_xor",
    "mul",
    "multiply",
    "nextafter",
    "remainder",
    "sub",
    "subtract",
    "true_divide",
    "eq",
    "ne",
    "le",
    "ge",
    "greater",
    "greater_equal",
    # "equal",
    "gt",
    # "isclose",
    "less_equal",
    "lt",
    "less",
    "maximum",
    "minimum",
    "fmax",
    "fmin",
    "not_equal",
]

INPLACE_BINARY_NAMES = [
    n + "_"
    for n in (
        list(
            set(BINARY_NAMES)
            - {
                "logaddexp",
                "logaddexp2",
                "equal",
                "fmin",
                "minimum",
                "maximum",
                "fmax",
            }
        )
    )
]


def get_mask(a):
    from maskedtensor import is_masked_tensor

    if is_masked_tensor(a):
        return a.masked_mask
    return None


def tensors_match(a, b):
    if a.layout == b.layout == torch.sparse_coo:
        a = a.to_dense()
        b = b.to_dense()
    return (a.dim() == b.dim()) and torch.eq(a, b).all().item()


def masks_match(a, b):
    from maskedtensor import is_masked_tensor

    if is_masked_tensor(a) and is_masked_tensor(b):
        mask_a = get_mask(a)
        mask_b = get_mask(b)
        return tensors_match(mask_a, mask_b)
    return True


def get_at_least_one_mask(a, b):
    from maskedtensor import is_masked_tensor

    assert is_masked_tensor(a) or is_masked_tensor(b)
    assert masks_match(a, b)
    if is_masked_tensor(a):
        return get_mask(a)
    return get_mask(b)


def torch_binary(fn_name):
    fn = getattr(torch.ops.aten, fn_name)
    from .passthrough import _map_mt_args_kwargs, _wrap_result

    def binary_fn(*args, **kwargs):
        assert len(kwargs) == 0
        if len(args) > 2:
            for a in args[1:]:
                assert not torch.is_tensor(a)
        mask_args, mask_kwargs = _map_mt_args_kwargs(
            args, kwargs, lambda x: x.masked_mask
        )
        if not masks_match(*args[:2]):
            raise ValueError(
                "Input masks must match. If you need support for this, please open an issue on Github."
            )
        if args[0].layout != args[1].layout:
            raise ValueError(
                "Inputs should match sparsity/density. If you need support this, please open an issue on Github."
            )
        data_args, data_kwargs = _map_mt_args_kwargs(
            args, kwargs, lambda x: x.masked_data
        )
        result_mask = get_at_least_one_mask(*args[:2])
        if args[0].layout == torch.sparse_coo:
            if not tensors_match(data_args[0].indices(), data_args[1].indices()):
                raise ValueError(
                    "Sparse indices must match. If you need support for this, please open an issue on Github."
                )
            i = data_args[0].indices()
            data_args[0] = data_args[0].values()
            data_args[1] = data_args[1].values()
            v = fn(*data_args)
            result_data = torch.sparse_coo_tensor(i, v)
        else:
            result_data = fn(*data_args)
            # sparse tensors don't have strides
            result_mask = result_mask.expand_as(result_data)
        return _wrap_result(result_data, result_mask)

    return binary_fn


def torch_inplace_binary(fn_name):
    fn = getattr(torch.ops.aten, fn_name)
    from .passthrough import _map_mt_args_kwargs

    def binary_fn(*args, **kwargs):
        assert len(kwargs) == 0
        if len(args) > 2:
            for a in args[1:]:
                assert not torch.is_tensor(a)
        mask_args, mask_kwargs = _map_mt_args_kwargs(
            args, kwargs, lambda x: x.masked_mask
        )
        if not masks_match(*args[:2]):
            raise ValueError(
                "Input masks must match. If you need support for this, please open an issue on Github."
            )
        data_args, data_kwargs = _map_mt_args_kwargs(
            args, kwargs, lambda x: x.masked_data
        )
        if args[0].layout == torch.sparse_coo:
            if not tensors_match(data_args[0].indices(), data_args[1].indices()):
                raise ValueError(
                    "Sparse indices must match. If you need support for this, please open an issue on Github."
                )
            i = data_args[0].indices()
            data_args[0] = data_args[0].values()
            data_args[1] = data_args[1].values()
            v = fn(*data_args)
            result_data = torch.sparse_coo_tensor(i, v)
        else:
            result_data = fn(*data_args)

        args[0]._set_data_mask(result_data, mask_args[0])
        return args[0]

    return binary_fn


NATIVE_BINARY_MAP = {
    getattr(torch.ops.aten, name): torch_binary(name) for name in BINARY_NAMES
}
NATIVE_INPLACE_BINARY_MAP = {
    getattr(torch.ops.aten, name): torch_inplace_binary(name)
    for name in INPLACE_BINARY_NAMES
}

NATIVE_BINARY_FNS = list(NATIVE_BINARY_MAP.keys())
NATIVE_INPLACE_BINARY_FNS = list(NATIVE_INPLACE_BINARY_MAP.keys())


def is_native_binary(fn):
    return fn in NATIVE_BINARY_FNS or fn in NATIVE_INPLACE_BINARY_FNS


def apply_native_binary(fn, *args, **kwargs):
    if fn in NATIVE_BINARY_FNS:
        return NATIVE_BINARY_MAP[fn](*args, **kwargs)
    if fn in NATIVE_INPLACE_BINARY_FNS:
        return NATIVE_INPLACE_BINARY_MAP[fn](*args, **kwargs)
    return NotImplemented

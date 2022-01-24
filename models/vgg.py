"""
    VGG model definition
    ported from https://github.com/pytorch/vision/blob/master/torchvision/models/vgg.py
"""

import math
import torch.nn as nn
import numpy as np

import curves

__all__ = ['VGG16', 'VGG16BN', 'VGG19', 'VGG19BN', 'get_size', 'compute_k']

def get_size(k, num_classes=100):
    return (3*9+2+2*2+4*3+8*8+8*num_classes)*k+\
          ((1+2*1+2*2+4*2+2*4*4+8*4+5*8*8)*9+\
           2*8*8)*k*k+num_classes
def compute_k(N, num_classes=100):
    a = ((1+2*1+2*2+4*2+2*4*4+8*4+5*8*8)*9+\
           2*8*8)
    b = (3*9+2+2*2+4*3+8*8+8*num_classes)
    c = num_classes
    return np.round((-b + np.sqrt(4*a*N+(b**2-4*a*c)))/2/a)


def get_config(depth, k=64):
    if depth == 16:
        return [[k, k], [k*2, k*2], [k*4, k*4, k*4], [k*8, k*8, k*8], [k*8, k*8, k*8]]
    else:
        return [[64, 64], [128, 128], [256, 256, 256, 256], [512, 512, 512, 512], [512, 512, 512, 512]]


def make_layers(config, batch_norm=False, fix_points=None):
    layer_blocks = nn.ModuleList()
    activation_blocks = nn.ModuleList()
    poolings = nn.ModuleList()

    kwargs = dict()
    conv = nn.Conv2d
    bn = nn.BatchNorm2d
    if fix_points is not None:
        kwargs['fix_points'] = fix_points
        conv = curves.Conv2d
        bn = curves.BatchNorm2d

    in_channels = 3
    for sizes in config:
        layer_blocks.append(nn.ModuleList())
        activation_blocks.append(nn.ModuleList())
        for channels in sizes:
            layer_blocks[-1].append(conv(in_channels, channels, kernel_size=3, padding=1, **kwargs))
            if batch_norm:
                layer_blocks[-1].append(bn(channels, **kwargs))
            activation_blocks[-1].append(nn.ReLU(inplace=True))
            in_channels = channels
        poolings.append(nn.MaxPool2d(kernel_size=2, stride=2))
    return layer_blocks, activation_blocks, poolings


class VGGBase(nn.Module):
    def __init__(self, num_classes, depth=16, batch_norm=False, k=64, p=0.5, use_InstanceNorm=False):
        super(VGGBase, self).__init__()
        config = get_config(depth, k=k)
        layer_blocks, activation_blocks, poolings = make_layers(config, batch_norm)
        self.layer_blocks = layer_blocks
        self.activation_blocks = activation_blocks
        self.poolings = poolings
        self.use_InstanceNorm = use_InstanceNorm

        self.classifier = nn.Sequential(
            nn.Dropout(p),
            nn.Linear(config[-1][-1], 8*k),
            nn.ReLU(inplace=True),
            nn.Dropout(p),
            nn.Linear(8*k, 8*k),
            nn.ReLU(inplace=True),
            nn.Linear(8*k, num_classes)
        )
        if use_InstanceNorm:
            self.normalization = nn.InstanceNorm1d(num_classes)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
                m.bias.data.zero_()

    def forward(self, x):
        for layers, activations, pooling in zip(self.layer_blocks, self.activation_blocks,
                                                self.poolings):
            for layer, activation in zip(layers, activations):
                x = layer(x)
                x = activation(x)
            x = pooling(x)
        x = x.view(x.size(0), -1)
        x = self.classifier(x)
        if self.use_InstanceNorm:
            x = x.view(x.size(0), 1, -1)
            x = self.normalization(x)
            x = x.view(x.size(0), -1)

        return x


class VGGCurve(nn.Module):
    def __init__(self, num_classes, fix_points, depth=16, k=64, batch_norm=False):
        super(VGGCurve, self).__init__()
        layer_blocks, activation_blocks, poolings = make_layers(get_config(depth, k=k),
                                                                batch_norm,
                                                                fix_points=fix_points)
        self.layer_blocks = layer_blocks
        self.activation_blocks = activation_blocks
        self.poolings = poolings

        self.dropout1 = nn.Dropout()
        self.fc1 = curves.Linear(512, 512, fix_points=fix_points)
        self.relu1 = nn.ReLU(inplace=True)
        self.dropout2 = nn.Dropout()
        self.fc2 = curves.Linear(512, 512, fix_points=fix_points)
        self.relu2 = nn.ReLU(inplace=True)
        self.fc3 = curves.Linear(512, num_classes, fix_points=fix_points)

        # Initialize weights
        for m in self.modules():
            if isinstance(m, curves.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                for i in range(m.num_bends):
                    getattr(m, 'weight_%d' % i).data.normal_(0, math.sqrt(2. / n))
                    getattr(m, 'bias_%d' % i).data.zero_()

    def forward(self, x, coeffs_t):
        for layers, activations, pooling in zip(self.layer_blocks, self.activation_blocks,
                                                self.poolings):
            for layer, activation in zip(layers, activations):
                x = layer(x, coeffs_t)
                x = activation(x)
            x = pooling(x)
        x = x.view(x.size(0), -1)

        x = self.dropout1(x)
        x = self.fc1(x, coeffs_t)
        x = self.relu1(x)

        x = self.dropout2(x)
        x = self.fc2(x, coeffs_t)
        x = self.relu2(x)

        x = self.fc3(x, coeffs_t)

        return x


class VGG16:
    def __init__(self):
        self.base = VGGBase
        self.curve = VGGCurve
        self.kwargs = {
            'depth': 16,
            'batch_norm': False
        }


class VGG16BN:
    def __init__(self):
        self.base = VGGBase
        self.curve = VGGCurve
        self.kwargs = {
            'depth': 16,
            'batch_norm': True
        }


class VGG19:
    def __init__(self):
        self.base = VGGBase
        self.curve = VGGCurve
        self.kwargs = {
            'depth': 19,
            'batch_norm': False
        }


class VGG19BN:
    def __init__(self):
        self.base = VGGBase
        self.curve = VGGCurve
        self.kwargs = {
            'depth': 19,
            'batch_norm': True
        }

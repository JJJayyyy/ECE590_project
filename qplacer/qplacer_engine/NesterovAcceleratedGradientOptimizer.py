import os
import sys
import time
import pickle
import numpy as np
import torch
from torch.optim.optimizer import Optimizer, required
import torch.nn as nn
import pdb

class NesterovAcceleratedGradientOptimizer(Optimizer):
    """
    @brief Follow the Nesterov's implementation of e-place algorithm 2
    http://cseweb.ucsd.edu/~jlu/papers/eplace-todaes14/paper.pdf
    """
    def __init__(self, params, lr=required, obj_and_grad_fn=required, constraint_fn=None):
        """
        @brief initialization
        @param params variable to optimize
        @param lr learning rate
        @param obj_and_grad_fn a callable function to get objective and gradient
        @param constraint_fn a callable function to force variables to satisfy all the constraints
        """
        if lr is not required and lr < 0.0:
            raise ValueError("Invalid learning rate: {}".format(lr))

        # u_k is major solution
        # v_k is reference solution
        # obj_k is the objective at v_k
        # a_k is optimization parameter
        # alpha_k is the step size
        # v_k_1 is previous reference solution
        # g_k_1 is gradient to v_k_1
        # obj_k_1 is the objective at v_k_1
        defaults = dict(lr=lr,
                u_k=[], v_k=[], g_k=[], obj_k=[], a_k=[], alpha_k=[],
                v_k_1=[], g_k_1=[], obj_k_1=[],
                v_kp1 = [None],
                obj_eval_count=0)
        super(NesterovAcceleratedGradientOptimizer, self).__init__(params, defaults)
        self.obj_and_grad_fn = obj_and_grad_fn
        self.constraint_fn = constraint_fn

        if len(self.param_groups) != 1:
            raise ValueError("Only parameters with single tensor is supported")

    def __setstate__(self, state):
        super(NesterovAcceleratedGradientOptimizer, self).__setstate__(state)

    def step(self, closure=None):
        """
        @brief Performs a single optimization step.
        @param closure A callable closure function that reevaluates the model and returns the loss.
        """
        loss = None
        if closure is not None:
            loss = closure()

        for group in self.param_groups:
            obj_and_grad_fn = self.obj_and_grad_fn
            constraint_fn = self.constraint_fn
            for i, p in enumerate(group['params']):
                if p.grad is None:
                    continue
                if not group['u_k']:
                    group['u_k'].append(p.data.clone())
                    # directly use p as v_k to save memory
                    group['v_k'].append(p)
                    obj, grad = obj_and_grad_fn(group['v_k'][i])
                    group['g_k'].append(grad.data.clone()) # must clone
                    group['obj_k'].append(obj.data.clone())
                u_k = group['u_k'][i]
                v_k = group['v_k'][i]
                g_k = group['g_k'][i]
                obj_k = group['obj_k'][i]
                if not group['a_k']:
                    group['a_k'].append(torch.ones(1, dtype=g_k.dtype, device=g_k.device))
                    group['v_k_1'].append(torch.autograd.Variable(torch.zeros_like(v_k), requires_grad=True))
                    group['v_k_1'][i].data.copy_(group['v_k'][i]-group['lr']*g_k)
                    obj, grad = obj_and_grad_fn(group['v_k_1'][i])
                    group['g_k_1'].append(grad.data)
                    group['obj_k_1'].append(obj.data.clone())
                a_k = group['a_k'][i]
                v_k_1 = group['v_k_1'][i]
                g_k_1 = group['g_k_1'][i]
                obj_k_1 = group['obj_k_1'][i]
                if not group['alpha_k']:
                    group['alpha_k'].append((v_k-v_k_1).norm(p=2) / (g_k-g_k_1).norm(p=2))
                alpha_k = group['alpha_k'][i]

                if group['v_kp1'][i] is None:
                    group['v_kp1'][i] = torch.autograd.Variable(torch.zeros_like(v_k), requires_grad=True)
                v_kp1 = group['v_kp1'][i]

                # line search with alpha_k as hint
                a_kp1 = (1 + (4*a_k.pow(2)+1).sqrt()) / 2
                coef = (a_k-1) / a_kp1
                alpha_kp1 = 0
                backtrack_cnt = 0
                max_backtrack_cnt = 10

                while True:
                    u_kp1 = v_k - alpha_k*g_k
                    v_kp1.data.copy_(u_kp1 + coef*(u_kp1-u_k))
                    constraint_fn(v_kp1)

                    f_kp1, g_kp1 = obj_and_grad_fn(v_kp1)

                    alpha_kp1 = torch.sqrt(torch.sum((v_kp1.data-v_k.data)**2) / torch.sum((g_kp1.data-g_k.data)**2))
                    backtrack_cnt += 1
                    group['obj_eval_count'] += 1
                    if alpha_kp1 > 0.95*alpha_k or backtrack_cnt >= max_backtrack_cnt:
                        alpha_k.data.copy_(alpha_kp1.data)
                        break
                    else:
                        alpha_k.data.copy_(alpha_kp1.data)

                v_k_1.data.copy_(v_k.data)
                g_k_1.data.copy_(g_k.data)
                obj_k_1.data.copy_(obj_k.data)

                u_k.data.copy_(u_kp1.data)
                v_k.data.copy_(v_kp1.data)
                g_k.data.copy_(g_kp1.data)
                obj_k.data.copy_(f_kp1.data)
                a_k.data.copy_(a_kp1.data)

        return loss

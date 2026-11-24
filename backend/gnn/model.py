"""Directed GraphSAGE: separate message passing along and against the money flow.

Money arriving at an account (fan-in, gathering) and money leaving it (fan-out, layering)
mean different things, so each layer aggregates in-neighbours and out-neighbours with their
own weights - the reverse-message-passing idea from IBM's Multi-GNN, in its simplest form.
"""
from __future__ import annotations

import torch
from torch import nn
from torch_geometric.nn import SAGEConv


class DirectedSAGELayer(nn.Module):
    def __init__(self, d_in: int, d_out: int):
        super().__init__()
        self.forward_conv = SAGEConv(d_in, d_out)   # aggregates senders of money into the account
        self.reverse_conv = SAGEConv(d_in, d_out)   # aggregates receivers the account pays

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        return self.forward_conv(x, edge_index) + self.reverse_conv(x, edge_index.flip(0))


class AccountGNN(nn.Module):
    def __init__(self, d_in: int, hidden: int = 32, dropout: float = 0.2):
        super().__init__()
        self.l1 = DirectedSAGELayer(d_in, hidden)
        self.l2 = DirectedSAGELayer(hidden, hidden)
        self.head = nn.Linear(hidden, 1)
        self.dropout = dropout

    def embed(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        h = torch.relu(self.l1(x, edge_index))
        h = nn.functional.dropout(h, self.dropout, self.training)
        return torch.relu(self.l2(h, edge_index))

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.embed(x, edge_index)
        return self.head(h).squeeze(-1), h

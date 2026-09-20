"""scheduler package"""
from scheduler.fcfs        import fcfs
from scheduler.sjf         import sjf
from scheduler.round_robin import round_robin
from scheduler.priority import priority_scheduling
from scheduler.priority_rr import priority_round_robin
from scheduler.srtf import srtf

__all__ = [
    "fcfs", "sjf", "round_robin", "priority_scheduling",
    "priority_round_robin", "srtf",
]

"""Loads every CSV in dataset/ into pandas DataFrames."""
from __future__ import annotations
import os
import pandas as pd


class Dataset:
    def __init__(self, dataset_dir: str):
        self.dir = dataset_dir
        self.requests = pd.read_csv(os.path.join(dataset_dir, "requests.csv"))
        self.sample_requests = pd.read_csv(os.path.join(dataset_dir, "sample_requests.csv"))
        self.profiles = pd.read_csv(os.path.join(dataset_dir, "financial_profiles.csv"))
        self.events = pd.read_csv(os.path.join(dataset_dir, "financial_events.csv"))
        self.exchange_rates = pd.read_csv(os.path.join(dataset_dir, "exchange_rates.csv"))
        self.payment_options = pd.read_csv(os.path.join(dataset_dir, "request_payment_options.csv"))
        self.messages = pd.read_csv(os.path.join(dataset_dir, "messages.csv"))
        self.images = pd.read_csv(os.path.join(dataset_dir, "images.csv"))
        self.media_dir = os.path.join(dataset_dir, "media", "images")

        # light normalisation
        for col in ["event_date", "settlement_date"]:
            self.events[col] = self.events[col].fillna(self.events["event_date"])
        self.profiles = self.profiles.set_index("user_id", drop=False)

    def profile(self, user_id):
        return self.profiles.loc[user_id]

    def events_for_user(self, user_id):
        return self.events[self.events.user_id == user_id]

    def messages_for_user(self, user_id):
        return self.messages[self.messages.user_id == user_id]

    def payment_options_for_request(self, request_id):
        return self.payment_options[self.payment_options.request_id == request_id]

    def images_for_request(self, request_id):
        return self.images[self.images.request_id == request_id]

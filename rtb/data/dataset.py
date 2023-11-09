import os
from pathlib import Path

import pandas as pd

from rtb.data.table import Table
from rtb.data.database import Database
from rtb.data.task import Task
from rtb.utils import rolling_window_sampler, one_window_sampler


class Dataset:
    r"""Base class for dataset. A dataset includes a database and tasks defined
    on it."""

    # name of dataset, to be specified by subclass
    name: str

    def __init__(self, root: str | os.PathLike) -> None:
        r"""Initializes the dataset."""

        self.root = root

        # download
        path = f"{root}/{self.name}/raw"
        if not Path(f"{path}/done").exists():
            self.download(path)
            Path(f"{path}/done").touch()

        path = f"{root}/{self.name}/processed/db"
        if not Path(f"{path}/done").exists():
            # process db
            db = self.process()

            # standardize db
            # db = self.standardize_db()

            # process and standardize are separate because
            # process() is implemented by each subclass, but
            # standardize() is common to all subclasses

            db.save(path)
            Path(f"{path}/done").touch()

        # load database
        self._db = Database.load(path)

        # we want to keep the database private, because it also contains
        # test information

        self.min_time, self.max_time = self._db.get_time_range()
        self.train_cutoff_time, self.val_cutoff_time = self.get_cutoff_times()

        self.tasks = self.get_tasks()

    def get_tasks(self) -> dict[str, Task]:
        r"""Returns a list of tasks defined on the dataset. To be implemented
        by subclass."""

        raise NotImplementedError

    def get_cutoff_times(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        r"""Returns the train and val cutoff times. To be implemented by
        subclass, but can implement a sensible default strategy here."""

        train_cutoff_time = self.min_time + 0.8 * (self.max_time - self.min_time)
        val_cutoff_time = self.min_time + 0.9 * (self.max_time - self.min_time)
        return train_cutoff_time, val_cutoff_time

    def download(self, path: str | os.PathLike) -> None:
        r"""Downloads the raw data to the path directory. To be implemented by
        subclass."""

        raise NotImplementedError

    def process(self) -> Database:
        r"""Processes the raw data into a database. To be implemented by
        subclass."""

        raise NotImplementedError

    def standardize_db(self, db: Database) -> Database:
        r"""
        - Add primary key column if not present.
        - Re-index primary key column with 0-indexed ints, if required.
        - Can still keep the original pkey column as a feature column (e.g. email).
        """

        raise NotImplementedError

    def db_snapshot(self, time_stamp: int) -> Database:
        r"""Returns a database with all rows upto time_stamp (if table is
        temporal, otherwise all rows)."""

        assert time_stamp <= self.val_cutoff_time

        return self._db.time_cutoff(time_stamp)

    @property
    def db_train(self) -> Database:
        return self.db_snapshot(self.train_cutoff_time)

    @property
    def db_val(self) -> Database:
        return self.db_snapshot(self.val_cutoff_time)

    def make_train_table(
        self,
        task_name: str,
        window_size: int | None = None,
        time_window_df: pd.DataFrame | None = None,
    ) -> Table:
        """Returns the train table for a task.

        User can either provide the window_size and get the train table
        generated by our default sampler, or explicitly provide the
        time_window_df obtained by their sampling strategy."""

        if time_window_df is None:
            assert window_size is not None
            # default sampler
            time_window_df = rolling_window_sampler(
                self.min_time,
                self.train_cutoff_time,
                window_size,
                stride=window_size,
            )

        task = self.tasks[task_name]
        return task.make_table(self.db_train, time_window_df)

    def make_val_table(
        self,
        task_name: str,
        window_size: int | None = None,
        time_window_df: pd.DataFrame | None = None,
    ) -> Table:
        r"""Returns the val table for a task.

        User can either provide the window_size and get the train table
        generated by our default sampler, or explicitly provide the
        time_window_df obtained by their sampling strategy."""

        if time_window_df is None:
            assert window_size is not None
            # default sampler
            time_window_df = one_window_sampler(
                self.train_cutoff_time,
                window_size,
            )

        task = self.tasks[task_name]
        return task.make_table(self.db_val, time_window_df)

    def make_test_table(self, task_name: str, window_size: int) -> Table:
        r"""Returns the test table for a task."""

        task = self.tasks[task_name]
        time_window_df = one_window_sampler(
            self.val_cutoff_time,
            window_size,
        )
        table = task.make_table(self._db, time_window_df)

        # hide the label information
        table.drop(columns=[task.target_col])

        return table

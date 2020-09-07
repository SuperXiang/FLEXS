import abc
import json
from datetime import datetime
import os

import numpy as np
import pandas as pd


class Explorer(abc.ABC):
    def __init__(
        self,
        model,
        landscape,
        name,
        rounds,
        ground_truth_measurements_per_round,
        model_queries_per_round,
        initial_sequence_data,
        log_file,
    ):
        self.model = model
        self.landscape = landscape
        self.name = name

        self.rounds = rounds
        self.ground_truth_measurements_per_round = ground_truth_measurements_per_round
        self.model_queries_per_round = model_queries_per_round
        self.initial_sequence_data = initial_sequence_data
        self.log_file = log_file

    @abc.abstractmethod
    def propose_sequences(self, measured_sequences):
        pass

    def _log(self, metadata, sequences, preds, true_score, current_round, verbose):
        if self.log_file is not None:

            # Create directory for `self.log_file` if necessary
            directory = os.path.split(self.log_file)[0]
            if directory != "" and not os.path.exists(directory):
                os.mkdir(directory)

            with open(self.log_file, "w") as f:
                # First write metadata
                json.dump(metadata, f)
                f.write("\n")

                # Then write pandas dataframe
                sequences.to_csv(f, index=False)

        if verbose:
            print(f"round: {current_round}, top: {true_score.max()}")

    def run(self, verbose=True):
        """Run the exporer."""

        self.model.cost = 0

        # Metadata about run that will be used for logging purposes
        metadata = {
            "run_id": datetime.now().strftime("%H:%M:%S-%m/%d/%Y"),
            "exp_name": self.name,
            "model_name": self.model.name,
            "landscape_name": self.landscape.name,
            "rounds": self.rounds,
            "ground_truth_measurements_per_round": self.ground_truth_measurements_per_round,
            "model_queries_per_round": self.model_queries_per_round,
        }

        # Initial sequences and their scores
        sequences = pd.DataFrame(
            {
                "sequence": self.initial_sequence_data,
                "model_score": np.nan,
                "true_score": self.landscape.get_fitness(self.initial_sequence_data),
                "round": 0,
                "model_cost": self.model.cost,
                "measurement_cost": len(self.initial_sequence_data),
            }
        )
        self._log(
            metadata,
            sequences,
            sequences["model_score"],
            sequences["true_score"],
            0,
            verbose,
        )

        # For each round, train model on available data, propose sequences,
        # measure them on the true landscape, add to available data, and repeat.
        for r in range(1, self.rounds + 1):
            self.model.train(
                sequences["sequence"].to_numpy(), sequences["true_score"].to_numpy()
            )

            seqs, preds = self.propose_sequences(sequences)
            true_score = self.landscape.get_fitness(seqs)

            if len(seqs) > self.ground_truth_measurements_per_round:
                raise ValueError(
                    "Must propose <= `self.ground_truth_measurements_per_round` sequences per round"
                )

            sequences = sequences.append(
                pd.DataFrame(
                    {
                        "sequence": seqs,
                        "model_score": preds,
                        "true_score": true_score,
                        "round": r,
                        "model_cost": self.model.cost,
                        "measurement_cost": len(sequences) + len(seqs),
                    }
                )
            )
            self._log(metadata, sequences, preds, true_score, r, verbose)

        return sequences, metadata

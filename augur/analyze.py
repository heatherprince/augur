"""Data analysis module.

This module runs the actual analysis of the data that
has been previously generated by the generate module.
At the moment it is a thin-wrapper to cosmosis.

"""

import firecrown
import pathlib
from .generate import firecrown_sanitize


def analyze(config):
    """ Analyzes the data, i.e. a thin wrapper to firecrown

    Parameters:
    ----------
    config : dict
        The yaml parsed dictional of the input yaml file
    """

    ana_config = config["analyze"]
    config, data = firecrown.parse(firecrown_sanitize(ana_config))
    firecrown.run_cosmosis(config, data, pathlib.Path(config["cosmosis"]["output_dir"]))

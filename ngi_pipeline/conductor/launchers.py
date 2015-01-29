#!/usr/bin/env python

from __future__ import print_function

import importlib
import os
import inspect

from ngi_pipeline.conductor.classes import NGIProject
from ngi_pipeline.database.classes import CharonSession, CharonError
from ngi_pipeline.database.filesystem import recreate_project_from_db
## FIXME this needs to be moved out of the engine-specific code and into a generic function
from ngi_pipeline.engines.piper_ngi.local_process_tracking import update_charon_with_local_jobs_status
from ngi_pipeline.log.loggers import minimal_logger
from ngi_pipeline.utils.classes import with_ngi_config
from ngi_pipeline.utils.communication import mail_analysis 


LOG = minimal_logger(__name__)

@with_ngi_config
def get_engine_for_BP(project, config=None, config_file_path=None):
    """returns a analysis engine module for the given project.

    :param NGIProject  project: The project to get the engine from.
    """
    charon_session = CharonSession()
    best_practice_analysis = charon_session.project_get(project.project_id)["best_practice_analysis"]
    try:
        analysis_engine_module_name=config["analysis"]["best_practice_analysis"][best_practice_analysis]["analysis_engine"]
    except KeyError:
        error_msg = ('No analysis engine for best practice analysis "{}" '
                     'specified in configuration file. '
                     'for project {}'.format(best_practice_analysis, project))
        raise RuntimeError(error_msg)
    try:
        analysis_module = importlib.import_module(analysis_engine_module_name)
    except ImportError as e:
        error_msg = ('project "{}" best practice analysis"{}": couldn\'t import '
                     'module "{}": {}'.format(project, best_practice_analysis,
                                              analysis_engine_module_name, e))
        raise RuntimeError(error_msg)
    return analysis_module

@with_ngi_config
def launch_analysis(projects_to_analyze, restart_failed_jobs=False,
                    exec_mode="sbatch", config=None, config_file_path=None):
    """Launch the appropriate analysis for each fastq file in the project.

    :param list projects_to_analyze: The list of projects (Project objects) to analyze
    :param dict config: The parsed NGI configuration file; optional/has default.
    :param str config_file_path: The path to the NGI configuration file; optional/has default.
    """
    for project in projects_to_analyze: # Get information from Charon regarding which best practice analyses to run
        engine=get_engine_for_BP(project, config, config_file_path)
        engine.local_process_tracking.update_charon_with_local_jobs_status()
    
    charon_session = CharonSession()
    for project in projects_to_analyze: # Get information from Charon regarding which best practice analyses to run
        project_status = charon_session.project_get(project.project_id)['status']
        if not project_status == "OPEN":
            error_text=('Data found on filesystem for project "{}" but Charon '
                      'reports its status is not OPEN ("{}"). Not launching '
                      'analysis for this project.'.format(project, project_status))
            LOG.error(error_text)
            mail_analysis(project_name = project.name, info_text = error_text)
            continue
        try:
            analysis_module=get_engine_for_BP(project)
        except (RuntimeError, KeyError, CharonError) as e: # BPA missing from Charon?
            LOG.error('Skipping project "{}" because of error: {}'.format(project, e))
            continue
        for sample in project:
            label = "{}/{}".format(project, sample)
            try:
                charon_reported_status = charon_session.sample_get(project.project_id,
                                                                   sample)['analysis_status']
            except (CharonError, KeyError) as e:
                LOG.warn('Unable to get required information from Charon for '
                          '{} -- forcing it to new: {}'.format(label, e))
                charon_reported_status = "TO_ANALYZE"
                charon_session.sample_update(project.project_id, sample.name,
                                             analysis_status=charon_reported_status)
            # Check Charon to ensure this hasn't already been processed
            if charon_reported_status in ("UNDER_ANALYSIS", "ANALYZED"):
                error_text = ('Charon reports seqrun analysis for project "{}" / sample "{}" '
                         'does not need processing '
                         ' (already "{}")'.format(project, sample, charon_reported_status))
                LOG.error(error_text)
                mail_analysis(project_name=project.name, sample_name=sample.name, engine_name=analysis_module.__name__, info_text=error_text)
                continue
            elif charon_reported_status == "FAILED":
                if not restart_failed_jobs:
                    error_text=('FAILED:  Project "{}" / sample "{}" Charon reports FAILURE, manual '
                              'investigation needed!'.format(project, sample))
                    LOG.error(error_text)
                    mail_analysis(project_name=project.name, sample_name=sample.name, engine_name=analysis_module.__name__, info_text=error_text)
                    continue
            try:
                LOG.info('Attempting to launch sample analysis for '
                         'project "{}" / sample "{}" / engine'
                         '"{}"'.format(project, sample, analysis_module.__name__))
                analysis_module.analyze(project=project,
                                        sample=sample,
                                        exec_mode=exec_mode)
            except Exception as e:
                error_text=('Cannot process project "{}" / sample "{}" / '
                          ' engine "{}" : {}'.format(project,sample,
                                                    analysis_module.__name__,e))
                LOG.error(error_text)
                mail_analysis(project_name=project.name, sample_name=sample.name, engine_name=analysis_module.__name__, info_text=e)
                continue

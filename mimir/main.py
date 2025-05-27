# main.py (refactored)
import os
from datetime import datetime
from argparse import ArgumentParser, Namespace

from mimir.runner.collect_info import CollectInfoRunner
from mimir.services.configuration.configuration import Configuration
from mimir.services.logger.logger import Logger

def build_create_config_parser(subparsers):
    create_config_parser = subparsers.add_parser(
        "create-config", help="Create the default configuration file"
    )
    create_config_parser.add_argument(
        "--config",
        type=str,
        default=os.path.join("config", "default_config.json"),
        help="Path to the config file",
    )

def build_collect_info_parser(subparsers):
    collect_info_parser = subparsers.add_parser(
        "collect-info", help="Collect tests with the specified configuration file"
    )
    collect_info_parser.add_argument(
        "--target",
        type=str,
        default=os.path.join("temp", "example-repo"),
        help="Path to the target repo",
    )
    collect_info_parser.add_argument(
        "--config",
        type=str,
        default=os.path.join("config", "default_config.json"),
        help="Path to the config file",
    )

def build_command_parser():
    parser = ArgumentParser(
        prog='mimir',
        description="Tool for analyzing code repositories and mapping tests.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")
    build_create_config_parser(subparsers)
    build_collect_info_parser(subparsers)
    return parser

async def run_command(args: Namespace):
    runtime = datetime.now()
    current_day = runtime.strftime("%Y-%m-%d")

    if args.command == "create-config":
        create_config_logger = Logger("logs", current_day, "create-config")
        Configuration.create_default_config(
            args.config, create_config_logger
        )

    elif args.command == "collect-info":
        collect_info_logger = Logger("logs", current_day, "collect-info")
        collect_info_config = Configuration(args.config, collect_info_logger)
        collect_info_runner = CollectInfoRunner(collect_info_config, collect_info_logger)
        await collect_info_runner.run_mimir_runner()
    else:
        build_command_parser().print_help()

def parse_args_from_cli():
    parser = build_command_parser()
    return parser.parse_args()

async def main():
    args = parse_args_from_cli()
    await run_command(args)

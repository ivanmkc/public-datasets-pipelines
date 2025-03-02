# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import argparse
import json
import pathlib
import re
import subprocess
import typing

import jinja2
from ruamel import yaml

yaml = yaml.YAML(typ="safe")


OPERATORS = {
    "BashOperator",
    "GoogleCloudStorageToBigQueryOperator",
    "GoogleCloudStorageToGoogleCloudStorageOperator",
    "GoogleCloudStorageDeleteOperator",
    "BigQueryOperator",
    "KubernetesPodOperator",
}

CURRENT_PATH = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_PATH.parent
DATASETS_PATH = PROJECT_ROOT / "datasets"
AIRFLOW_TEMPLATES_PATH = PROJECT_ROOT / "templates" / "airflow"

TEMPLATE_PATHS = {
    "dag": AIRFLOW_TEMPLATES_PATH / "dag.py.jinja2",
    "task": AIRFLOW_TEMPLATES_PATH / "task.py.jinja2",
    "license": AIRFLOW_TEMPLATES_PATH / "license_header.py.jinja2",
    "dag_context": AIRFLOW_TEMPLATES_PATH / "dag_context.py.jinja2",
    "default_args": AIRFLOW_TEMPLATES_PATH / "default_args.py.jinja2",
}

AIRFLOW_VERSION = "1.10.14"
AIRFLOW_IMPORTS = json.load(open(CURRENT_PATH / "dag_imports.json"))


def main(dataset_id: str, pipeline_id: str, env: str):
    pipeline_dir = DATASETS_PATH / dataset_id / pipeline_id
    config = yaml.load((pipeline_dir / "pipeline.yaml").read_text())

    validate_dag_id_existence_and_format(config)
    dag_contents = generate_dag(config, dataset_id)

    target_path = pipeline_dir / f"{pipeline_id}_dag.py"
    create_file_in_dot_and_project_dirs(
        dataset_id,
        pipeline_id,
        dag_contents,
        target_path.name,
        PROJECT_ROOT / f".{env}",
    )
    write_to_file(dag_contents, target_path)

    copy_custom_callables_to_dot_dir(
        dataset_id,
        pipeline_id,
        PROJECT_ROOT / f".{env}",
    )

    print_airflow_variables(dataset_id, dag_contents, env)
    format_python_code(target_path)


def generate_dag(config: dict, dataset_id: str) -> str:
    return jinja2.Template(TEMPLATE_PATHS["dag"].read_text()).render(
        package_imports=generate_package_imports(config),
        default_args=generate_default_args(config),
        dag_context=generate_dag_context(config, dataset_id),
        tasks=generate_tasks(config),
        graph_paths=config["dag"]["graph_paths"],
    )


def generate_package_imports(config: dict) -> str:
    contents = {"from airflow import DAG"}
    for task in config["dag"]["tasks"]:
        contents.add(AIRFLOW_IMPORTS[AIRFLOW_VERSION][task["operator"]]["import"])
    return "\n".join(contents)


def generate_tasks(config: dict) -> list:
    contents = []
    for task in config["dag"]["tasks"]:
        contents.append(generate_task_contents(task))
    return contents


def generate_default_args(config: dict) -> str:
    return jinja2.Template(TEMPLATE_PATHS["default_args"].read_text()).render(
        default_args=dag_init(config)["default_args"]
    )


def generate_dag_context(config: dict, dataset_id: str) -> str:
    dag_params = dag_init(config)
    return jinja2.Template(TEMPLATE_PATHS["dag_context"].read_text()).render(
        dag_init=dag_params,
        namespaced_dag_id=namespaced_dag_id(dag_params["dag_id"], dataset_id),
    )


def generate_task_contents(task: dict) -> str:
    validate_task(task)
    return jinja2.Template(TEMPLATE_PATHS["task"].read_text()).render(
        **task,
        namespaced_operator=AIRFLOW_IMPORTS[AIRFLOW_VERSION][task["operator"]]["class"],
    )


def dag_init(config: dict) -> dict:
    return config["dag"].get("initialize") or config["dag"].get("init")


def namespaced_dag_id(dag_id: str, dataset_id: str) -> str:
    return f"{dataset_id}.{dag_id}"


def validate_dag_id_existence_and_format(config: dict):
    init = dag_init(config)
    if not init.get("dag_id"):
        raise KeyError("Missing required parameter:`dag_id`")

    dag_id_regex = r"^[a-zA-Z0-9_\.]*$"
    if not re.match(dag_id_regex, init["dag_id"]):
        raise ValueError(
            "`dag_id` must contain only alphanumeric, dot, and underscore characters"
        )


def validate_task(task: dict):
    if not task.get("operator"):
        raise KeyError(f"`operator` key must exist in {task}")

    if not task["operator"] in OPERATORS:
        raise ValueError(f"`task.operator` must be one of {list(OPERATORS)}")

    if not task["args"].get("task_id"):
        raise KeyError(f"`args.task_id` key must exist in {task}")


def list_subdirs(path: pathlib.Path) -> typing.List[pathlib.Path]:
    """Returns a list of subdirectories"""
    subdirs = [f for f in path.iterdir() if f.is_dir() and not f.name[0] in (".", "_")]
    return subdirs


def write_to_file(contents: str, filepath: pathlib.Path):
    license_header = pathlib.Path(TEMPLATE_PATHS["license"]).read_text() + "\n"
    with open(filepath, "w") as file_:
        file_.write(license_header + contents.replace(license_header, ""))


def format_python_code(target_file: pathlib.Path):
    subprocess.Popen(f"black -q {target_file}", stdout=subprocess.PIPE, shell=True)
    subprocess.check_call(["isort", "--profile", "black", "."], cwd=PROJECT_ROOT)


def print_airflow_variables(dataset_id: str, dag_contents: str, env: str):
    var_regex = r"\{{2}\s*var.([a-zA-Z0-9_\.]*)?\s*\}{2}"
    print(
        f"\nThe following Airflow variables must be set in"
        f"\n\n  .{env}/datasets/{dataset_id}/{dataset_id}_variables.json"
        "\n\nusing JSON dot notation:"
        "\n"
    )
    for var in sorted(
        list(set(re.findall(var_regex, dag_contents))), key=lambda v: v.count(".")
    ):
        if var.startswith("json."):
            var = var.replace("json.", "", 1)
        elif var.startswith("value."):
            var = var.replace("value.", "", 1)
        print(f"  - {var}")
    print()


def create_file_in_dot_and_project_dirs(
    dataset_id: str,
    pipeline_id: str,
    contents: str,
    filename: str,
    env_dir: pathlib.Path,
):
    print("\nCreated\n")
    for prefix in (
        env_dir / "datasets" / dataset_id / pipeline_id,
        DATASETS_PATH / dataset_id / pipeline_id,
    ):
        prefix.mkdir(parents=True, exist_ok=True)
        target_path = prefix / filename
        write_to_file(contents + "\n", target_path)
        print(f"  - {target_path.relative_to(PROJECT_ROOT)}")


def copy_custom_callables_to_dot_dir(
    dataset_id: str, pipeline_id: str, env_dir: pathlib.Path
):
    callables_dir = DATASETS_PATH / dataset_id / pipeline_id / "custom"
    if callables_dir.exists():
        target_dir = env_dir / "datasets" / dataset_id / pipeline_id
        target_dir.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            ["cp", "-rf", str(callables_dir), str(target_dir)], cwd=PROJECT_ROOT
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate Terraform infra code for BigQuery datasets"
    )
    parser.add_argument(
        "-d",
        "--dataset",
        required=True,
        type=str,
        dest="dataset",
        help="The directory name of the dataset.",
    )
    parser.add_argument(
        "-p",
        "--pipeline",
        type=str,
        dest="pipeline",
        help="The directory name of the pipeline",
    )
    parser.add_argument(
        "-e",
        "--env",
        type=str,
        default="dev",
        dest="env",
        help="The stage used for the resources: dev|staging|prod",
    )
    parser.add_argument(
        "--all-pipelines", required=False, dest="all_pipelines", action="store_true"
    )

    args = parser.parse_args()

    if args.all_pipelines:
        for pipeline_dir in list_subdirs(DATASETS_PATH / args.dataset):
            main(args.dataset, pipeline_dir.name, args.env)
    else:
        main(args.dataset, args.pipeline, args.env)

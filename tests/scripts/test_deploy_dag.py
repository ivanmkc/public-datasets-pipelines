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


import pathlib
import shutil
import subprocess
import tempfile
import typing

import pytest
from ruamel import yaml

from scripts import deploy_dag, generate_dag

yaml = yaml.YAML(typ="safe")

PROJECT_ROOT = generate_dag.PROJECT_ROOT
SAMPLE_YAML_PATHS = {
    "dataset": PROJECT_ROOT / "samples" / "dataset.yaml",
    "pipeline": PROJECT_ROOT / "samples" / "pipeline.yaml",
    "variables": PROJECT_ROOT / "samples" / "dataset_variables.json",
}

ENV_PATH = generate_dag.PROJECT_ROOT / ".test"
ENV_DATASETS_PATH = ENV_PATH / "datasets"


@pytest.fixture
def dataset_path() -> typing.Iterator[pathlib.Path]:
    with tempfile.TemporaryDirectory(
        dir=generate_dag.DATASETS_PATH, suffix="_dataset"
    ) as dir_path:
        yield pathlib.Path(dir_path)


@pytest.fixture
def pipeline_path(
    dataset_path: pathlib.Path, suffix="_pipeline"
) -> typing.Iterator[pathlib.Path]:
    with tempfile.TemporaryDirectory(dir=dataset_path, suffix=suffix) as dir_path:
        yield pathlib.Path(dir_path)


@pytest.fixture
def airflow_home() -> typing.Iterator[pathlib.Path]:
    with tempfile.TemporaryDirectory(suffix="_airflow_home") as airflow_home_path:
        yield pathlib.Path(airflow_home_path)


@pytest.fixture
def env() -> str:
    return "test"


def copy_config_files_and_set_tmp_folder_names_as_ids(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path
):
    shutil.copyfile(SAMPLE_YAML_PATHS["dataset"], dataset_path / "dataset.yaml")
    shutil.copyfile(SAMPLE_YAML_PATHS["pipeline"], pipeline_path / "pipeline.yaml")

    dataset_config = yaml.load(dataset_path / "dataset.yaml")
    dataset_yaml_str = (
        (dataset_path / "dataset.yaml")
        .read_text()
        .replace(
            f"name: {dataset_config['dataset']['name']}", f"name: {dataset_path.name}"
        )
    )
    generate_dag.write_to_file(dataset_yaml_str, dataset_path / "dataset.yaml")

    pipeline_config = yaml.load(pipeline_path / "pipeline.yaml")
    pipeline_yaml_str = (
        (pipeline_path / "pipeline.yaml")
        .read_text()
        .replace(
            f"dag_id: {pipeline_config['dag']['initialize']['dag_id']}",
            f"dag_id: {pipeline_path.name}",
        )
    )
    generate_dag.write_to_file(pipeline_yaml_str, pipeline_path / "pipeline.yaml")


def create_airflow_folders(airflow_home: pathlib.Path):
    (airflow_home / "dags").mkdir(parents=True, exist_ok=True)
    (airflow_home / "data").mkdir(parents=True, exist_ok=True)


def setup_dag_and_variables(
    dataset_path: pathlib.Path,
    pipeline_path: pathlib.Path,
    airflow_home: pathlib.Path,
    env: str,
    variables_filename: str,
):
    copy_config_files_and_set_tmp_folder_names_as_ids(dataset_path, pipeline_path)
    create_airflow_folders(airflow_home)

    generate_dag.main(
        dataset_id=dataset_path.name, pipeline_id=pipeline_path.name, env=env
    )

    shutil.copyfile(
        SAMPLE_YAML_PATHS["variables"],
        ENV_DATASETS_PATH / dataset_path.name / variables_filename,
    )


def test_script_always_requires_dataset_arg(
    dataset_path: pathlib.Path,
    pipeline_path: pathlib.Path,
    airflow_home: pathlib.Path,
    env: str,
):
    setup_dag_and_variables(
        dataset_path,
        pipeline_path,
        airflow_home,
        env,
        f"{dataset_path.name}_variables.json",
    )

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "python",
                "scripts/deploy_dag.py",
                "--env",
                env,
                "--airflow-home",
                str(airflow_home),
                "--local",
            ],
            cwd=deploy_dag.PROJECT_ROOT,
        )

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "python",
                "scripts/deploy_dag.py",
                "--env",
                env,
            ],
            cwd=deploy_dag.PROJECT_ROOT,
        )

    subprocess.check_call(
        [
            "python",
            "scripts/deploy_dag.py",
            "--dataset",
            dataset_path.name,
            "--env",
            env,
            "--airflow-home",
            str(airflow_home),
            "--local",
        ],
        cwd=deploy_dag.PROJECT_ROOT,
    )


def test_script_without_local_flag_requires_cloud_composer_args(env: str):
    with pytest.raises(subprocess.CalledProcessError):
        # No --composer-env parameter
        subprocess.check_call(
            [
                "python",
                "scripts/deploy_dag.py",
                "--dataset",
                "some_test_dataset",
                "--env",
                env,
                "--composer-bucket",
                "us-east4-composer-env-bucket",
                "--composer-region",
                "us-east4",
            ],
            cwd=deploy_dag.PROJECT_ROOT,
        )

    with pytest.raises(subprocess.CalledProcessError):
        # No --composer-bucket parameter
        subprocess.check_call(
            [
                "python",
                "scripts/deploy_dag.py",
                "--dataset",
                "some_test_dataset",
                "--env",
                env,
                "--composer-env",
                "test-composer-env",
                "--composer-region",
                "us-east4",
            ],
            cwd=deploy_dag.PROJECT_ROOT,
        )

    with pytest.raises(subprocess.CalledProcessError):
        # No --composer-region parameter
        subprocess.check_call(
            [
                "python",
                "scripts/deploy_dag.py",
                "--dataset",
                "some_test_dataset",
                "--env",
                env,
                "--composer-env",
                "test-composer-env",
                "--composer-bucket",
                "us-east4-composer-env-bucket",
            ],
            cwd=deploy_dag.PROJECT_ROOT,
        )


def test_script_with_local_flag_requires_airflow_home_to_be_an_existing_directory(
    dataset_path: pathlib.Path,
    pipeline_path: pathlib.Path,
    airflow_home: pathlib.Path,
    env: str,
):
    setup_dag_and_variables(
        dataset_path,
        pipeline_path,
        airflow_home,
        env,
        f"{dataset_path.name}_variables.json",
    )

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "python",
                "scripts/deploy_dag.py",
                "--dataset",
                dataset_path.name,
                "--env",
                env,
                "--airflow-home",
                tempfile.NamedTemporaryFile().name,
                "--local",
            ],
            cwd=deploy_dag.PROJECT_ROOT,
        )

    assert airflow_home.exists()
    subprocess.check_call(
        [
            "python",
            "scripts/deploy_dag.py",
            "--dataset",
            dataset_path.name,
            "--env",
            env,
            "--airflow-home",
            str(airflow_home),
            "--local",
        ],
        cwd=deploy_dag.PROJECT_ROOT,
    )


def test_script_with_local_flag_copies_files_to_local_airflow_env(
    dataset_path: pathlib.Path,
    pipeline_path: pathlib.Path,
    airflow_home: pathlib.Path,
    env: str,
):
    dag_filename = f"{dataset_path.name}__{pipeline_path.name}_dag.py"
    variables_filename = f"{dataset_path.name}_variables.json"

    setup_dag_and_variables(
        dataset_path,
        pipeline_path,
        airflow_home,
        env,
        f"{dataset_path.name}_variables.json",
    )

    deploy_dag.main(
        local=True,
        env_path=ENV_PATH,
        dataset_id=dataset_path.name,
        airflow_home=airflow_home,
        composer_env=None,
        composer_bucket=None,
        composer_region=None,
    )

    assert (airflow_home / "data" / "variables" / variables_filename).exists()
    assert (airflow_home / "dags" / dag_filename).exists()


def test_script_with_local_flag_copies_custom_callables_dir_to_local_airflow_env(
    dataset_path: pathlib.Path,
    pipeline_path: pathlib.Path,
    airflow_home: pathlib.Path,
    env: str,
):
    callables_dir = pipeline_path / "custom"
    callables_dir.mkdir(parents=True, exist_ok=True)
    custom_file = tempfile.NamedTemporaryFile(suffix=".py", dir=callables_dir)

    setup_dag_and_variables(
        dataset_path,
        pipeline_path,
        airflow_home,
        env,
        f"{dataset_path.name}_variables.json",
    )

    deploy_dag.main(
        local=True,
        env_path=ENV_PATH,
        dataset_id=dataset_path.name,
        airflow_home=airflow_home,
        composer_env=None,
        composer_bucket=None,
        composer_region=None,
    )

    target_callables_dir = (
        airflow_home / "dags" / dataset_path.name / pipeline_path.name / "custom"
    )
    assert target_callables_dir.exists()
    assert target_callables_dir.is_dir()
    assert (target_callables_dir / custom_file.name.split("/")[-1]).exists()
    assert not (target_callables_dir / custom_file.name.split("/")[-1]).is_dir()

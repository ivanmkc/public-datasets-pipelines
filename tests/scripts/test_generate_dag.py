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

from scripts import generate_dag

yaml = yaml.YAML(typ="safe")

PROJECT_ROOT = generate_dag.PROJECT_ROOT
SAMPLE_YAML_PATHS = {
    "dataset": PROJECT_ROOT / "samples" / "dataset.yaml",
    "pipeline": PROJECT_ROOT / "samples" / "pipeline.yaml",
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
def pipeline_path(dataset_path, suffix="_pipeline") -> typing.Iterator[pathlib.Path]:
    with tempfile.TemporaryDirectory(dir=dataset_path, suffix=suffix) as dir_path:
        yield pathlib.Path(dir_path)


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


@pytest.fixture
def env() -> str:
    return "test"


def test_tf_templates_exist():
    for _, filepath in generate_dag.TEMPLATE_PATHS.items():
        assert filepath.exists()


def test_main_generates_dag_files(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path, env: str
):
    copy_config_files_and_set_tmp_folder_names_as_ids(dataset_path, pipeline_path)

    generate_dag.main(dataset_path.name, pipeline_path.name, env)

    for path_prefix in (
        pipeline_path,
        ENV_DATASETS_PATH / dataset_path.name / pipeline_path.name,
    ):
        assert (path_prefix / f"{pipeline_path.name}_dag.py").exists()


def test_main_copies_custom_dir_if_it_exists(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path, env: str
):
    copy_config_files_and_set_tmp_folder_names_as_ids(dataset_path, pipeline_path)
    custom_path = dataset_path / pipeline_path.name / "custom"
    custom_path.mkdir(parents=True, exist_ok=True)

    generate_dag.main(dataset_path.name, pipeline_path.name, env)

    for path_prefix in (
        pipeline_path,
        ENV_DATASETS_PATH / dataset_path.name / pipeline_path.name,
    ):
        assert (path_prefix / "custom").exists()
        assert (path_prefix / "custom").is_dir()


def test_main_only_depends_on_pipeline_yaml(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path, env: str
):
    shutil.copyfile(SAMPLE_YAML_PATHS["pipeline"], pipeline_path / "pipeline.yaml")

    assert not (dataset_path / "dataset.yaml").exists()

    generate_dag.main(dataset_path.name, pipeline_path.name, env)

    for path_prefix in (
        pipeline_path,
        ENV_DATASETS_PATH / dataset_path.name / pipeline_path.name,
    ):
        assert (path_prefix / f"{pipeline_path.name}_dag.py").exists()


def test_main_errors_out_on_nonexisting_pipeline_path(dataset_path, env: str):
    with pytest.raises(FileNotFoundError):
        generate_dag.main(dataset_path.name, "non_existing_pipeline", env)


def test_main_errors_out_on_nonexisting_pipeline_yaml(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path, env: str
):
    assert not (pipeline_path / "pipeline.yaml").exists()

    with pytest.raises(FileNotFoundError):
        generate_dag.main(dataset_path.name, pipeline_path.name, env)


def test_checks_for_task_operator_and_id():
    valid_task = {
        "operator": "GoogleCloudStorageToBigQueryOperator",
        "args": {"task_id": "load_gcs_to_bq"},
    }
    generate_dag.validate_task(valid_task)

    non_existing_operator = {
        "operator": "NonExisting",
        "args": {"task_id": "load_gcs_to_bq"},
    }
    with pytest.raises(ValueError):
        generate_dag.validate_task(non_existing_operator)

    non_existing_task_id = {
        "operator": "GoogleCloudStorageToBigQueryOperator",
        "args": {"some_arg": "some_val"},
    }
    with pytest.raises(KeyError):
        generate_dag.validate_task(non_existing_task_id)


def test_generated_dag_file_loads_properly_in_python(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path, env: str
):
    copy_config_files_and_set_tmp_folder_names_as_ids(dataset_path, pipeline_path)

    generate_dag.main(dataset_path.name, pipeline_path.name, env)

    dag_filename = f"{pipeline_path.name}_dag.py"

    for cwd in (
        pipeline_path,
        ENV_DATASETS_PATH / dataset_path.name / pipeline_path.name,
    ):
        subprocess.check_call(["python", dag_filename], cwd=cwd)


def test_generated_dag_files_contain_license_headers(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path, env: str
):
    copy_config_files_and_set_tmp_folder_names_as_ids(dataset_path, pipeline_path)

    generate_dag.main(dataset_path.name, pipeline_path.name, env)

    license_header = pathlib.Path(generate_dag.TEMPLATE_PATHS["license"]).read_text()

    for path_prefix in (
        pipeline_path,
        ENV_DATASETS_PATH / dataset_path.name / pipeline_path.name,
    ):
        assert (path_prefix / f"{pipeline_path.name}_dag.py").read_text().count(
            license_header
        ) == 1


def test_existence_of_dag_id():
    with pytest.raises(KeyError):
        generate_dag.validate_dag_id_existence_and_format(
            {"dag": {"initialize": {"default_view": "graph"}}}
        )


def test_dag_id_contains_only_alphanumeric_dots_and_underscores():
    with pytest.raises(ValueError):
        generate_dag.validate_dag_id_existence_and_format(
            {"dag": {"initialize": {"dag_id": "invalid id"}}}
        )

    with pytest.raises(ValueError):
        generate_dag.validate_dag_id_existence_and_format(
            {"dag": {"initialize": {"dag_id": "invalid/id"}}}
        )

    with pytest.raises(ValueError):
        generate_dag.validate_dag_id_existence_and_format(
            {"dag": {"initialize": {"dag_id": "invalid:id"}}}
        )

    generate_dag.validate_dag_id_existence_and_format(
        {"dag": {"initialize": {"dag_id": "test_dataset_123.test_dag_456"}}}
    )


def test_dag_id_in_py_file_is_prepended_with_dataset_id(
    dataset_path: pathlib.Path, pipeline_path: pathlib.Path, env: str
):
    copy_config_files_and_set_tmp_folder_names_as_ids(dataset_path, pipeline_path)

    generate_dag.main(dataset_path.name, pipeline_path.name, env)

    dagpy_contents = (pipeline_path / f"{pipeline_path.name}_dag.py").read_text()
    expected_dag_id = generate_dag.namespaced_dag_id(
        pipeline_path.name, dataset_path.name
    )
    assert f'dag_id="{expected_dag_id}"' in dagpy_contents

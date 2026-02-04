import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import ANY
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, Request

from . import config

opener = urllib.request.build_opener(
    HTTPSHandler(debuglevel=config.HTTPS_DEBUG_LEVEL),
)


@dataclass(frozen=True)
class Repo:
    base_dir: Path

    clone_url: str
    default_branch: str
    description: str
    html_url: str
    name: str
    updated_at: datetime

    @property
    def path(self) -> Path:
        return self.base_dir.joinpath(self.name)

    def clone(self) -> None:
        print("git: clone", self.name)
        # Cannot use `--mirror` due to
        # https://stackoverflow.com/questions/34265266/remote-rejected-errors-after-mirroring-a-git-repository.
        subprocess.run(
            ["git", "clone", "--bare", self.clone_url, self.path],
            check=True,
        )

    def push(self, remote: str) -> None:
        print("git: push", self.name, remote)
        subprocess.run(
            ["git", "push", "--mirror", remote],
            cwd=self.path,
            check=True,
        )


class Codeberg:
    def __init__(self, username: str, token: str) -> None:
        self.username = username
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("codeberg: sync", repo.name)
        remote = f"git@codeberg.org:{self.username}/{repo.name}.git"
        self.create(repo.name)
        repo.push(remote)
        self.update(
            name=repo.name,
            data={
                "default_branch": repo.default_branch,
                "description": repo.description,
                "website": repo.html_url,
            },
        )

    def create(self, name: str) -> None:
        print("codeberg: create", name)
        # https://codeberg.org/api/swagger
        request = Request(
            url="https://codeberg.org/api/v1/user/repos",
            method="POST",
            headers={
                "authorization": f"token {self.token}",
                "content-type": "application/json",
            },
            data=json.dumps({"name": name}).encode(),
        )
        try:
            opener.open(request)
        except HTTPError as e:
            if e.code == 409:  # 409 Conflict: repo already exists
                return
            raise

    def update(self, name: str, data: dict) -> None:
        print("codeberg: update", name)
        # https://codeberg.org/api/swagger
        request = Request(
            url=f"https://codeberg.org/api/v1/repos/{self.username}/{name}",
            method="PATCH",
            headers={
                "authorization": f"token {self.token}",
                "content-type": "application/json",
            },
            data=json.dumps(data).encode(),
        )
        opener.open(request)


class Github:
    def __init__(self, username: str, token: str) -> None:
        self.username = username
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("github: sync", repo.name)
        remote = f"git@github.com:{self.username}/{repo.name}.git"
        self.create(repo.name)
        repo.push(remote)
        self.update(
            name=repo.name,
            data={
                "default_branch": repo.default_branch,
                "description": repo.description,
                "homepage": repo.html_url,
            },
        )

    def create(self, name: str) -> None:
        print("github: create", name)
        # https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#create-a-repository-for-the-authenticated-user
        request = Request(
            url="https://api.github.com/user/repos",
            method="POST",
            headers={
                "authorization": f"Bearer {self.token}",
                "content-type": "application/json",
                "x-github-api-version": "2022-11-28",
            },
            data=json.dumps({"name": name}).encode(),
        )
        try:
            opener.open(request)
        except HTTPError as e:
            if json.load(e) != {
                "documentation_url": ANY,
                "errors": [
                    {
                        "code": "custom",
                        "field": "name",
                        "message": "name already exists on this account",
                        "resource": "Repository",
                    }
                ],
                "message": ANY,
                "status": ANY,
            }:
                raise

    def update(self, name: str, data: dict) -> None:
        print("github: update", name)
        # https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#update-a-repository
        request = Request(
            url=f"https://api.github.com/repos/{self.username}/{name}",
            method="PATCH",
            headers={
                "authorization": f"Bearer {self.token}",
                "content-type": "application/json",
                "x-github-api-version": "2022-11-28",
            },
            data=json.dumps(data).encode(),
        )
        opener.open(request)


class Gitlab:
    def __init__(self, username: str, token: str) -> None:
        self.username = username
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("gitlab: sync", repo.name)
        remote = f"git@gitlab.com:{self.username}/{repo.name}.git"
        self.create(repo.name)
        # GitLab repos are created with a protected main branch by default,
        # which means we're not allowed to force push. Unprotect all branches.
        self.unprotect_all_branches(repo.name)
        repo.push(remote)
        self.update(
            name=repo.name,
            data={
                "default_branch": repo.default_branch,
                "description": repo.description + "\n\n" + repo.html_url,
            },
        )

    def create(self, name: str) -> None:
        print("gitlab: create", name)
        # https://docs.gitlab.com/api/projects/#create-a-project
        request = Request(
            url="https://gitlab.com/api/v4/projects",
            method="POST",
            headers={
                "content-type": "application/json",
                "private-token": self.token,
            },
            data=json.dumps(
                {
                    "path": name,
                    "visibility": "public",
                }
            ).encode(),
        )
        try:
            opener.open(request)
        except HTTPError as e:
            if json.load(e) != {
                "message": {
                    "name": ["has already been taken"],
                    "path": ["has already been taken"],
                    "project_namespace.name": ["has already been taken"],
                }
            }:
                raise

    def update(self, name: str, data: dict) -> dict:
        print("gitlab: update", name)
        # https://docs.gitlab.com/api/projects/#edit-a-project
        request = Request(
            url=f"https://gitlab.com/api/v4/projects/{self.username}%2F{name}",
            method="PUT",
            headers={
                "content-type": "application/json",
                "private-token": self.token,
            },
            data=json.dumps(data).encode(),
        )
        return json.load(opener.open(request))

    def unprotect_all_branches(self, name: str) -> None:
        print("gitlab: unprotect all branches", name)
        # https://docs.gitlab.com/api/protected_branches/#list-protected-branches
        request = Request(
            url=f"https://gitlab.com/api/v4/projects/{self.username}%2F{name}/protected_branches",
            method="GET",
            headers={
                "private-token": self.token,
            },
        )
        protected_branches = json.load(opener.open(request))
        for branch in protected_branches:
            # https://docs.gitlab.com/api/protected_branches/#unprotect-repository-branches
            request = Request(
                url=f"https://gitlab.com/api/v4/projects/{self.username}%2F{name}/protected_branches/{branch['name']}",
                method="DELETE",
                headers={
                    "private-token": self.token,
                },
            )
            opener.open(request)


class Sourcehut:
    def __init__(self, username: str, token: str) -> None:
        self.username = username
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("sourcehut: sync", repo.name)
        remote = f"git@git.sr.ht:~{self.username}/{repo.name}"
        self.create(repo.name)
        repo.push(remote)
        self.update(
            id=self.get(repo.name),
            data={
                "description": repo.description,
                "HEAD": repo.default_branch,
            },
        )

    def get(self, name: str) -> int:
        print("sourcehut: get", name)
        # https://man.sr.ht/git.sr.ht/graphql.md
        request = Request(
            url="https://git.sr.ht/query",
            method="POST",
            headers={
                "authorization": f"bearer {self.token}",
                "content-type": "application/json",
            },
            data=json.dumps(
                {
                    "query": "query getRepositoryId($name: String!) { me { repository(name: $name) { id } } }",
                    "variables": {"name": name},
                }
            ).encode(),
        )
        response = json.load(opener.open(request))
        if "errors" in response:
            raise Exception(response)
        return response["data"]["me"]["repository"]["id"]

    def create(self, name: str) -> None:
        print("sourcehut: create", name)
        # https://man.sr.ht/git.sr.ht/graphql.md
        request = Request(
            url="https://git.sr.ht/query",
            method="POST",
            headers={
                "authorization": f"bearer {self.token}",
                "content-type": "application/json",
            },
            data=json.dumps(
                {
                    "query": "mutation createRepository($name: String!) { createRepository(name: $name, visibility: PUBLIC) { id } }",
                    "variables": {"name": name},
                }
            ).encode(),
        )
        response = json.load(opener.open(request))
        if "errors" in response:
            if response != {
                "data": ANY,
                "errors": [
                    {
                        "extensions": ANY,
                        "message": "A repository with this name already exists.",
                        "path": ["createRepository"],
                    }
                ],
            }:
                raise Exception(response)

    def update(self, id: int, data: dict) -> None:
        print("sourcehut: update", id)
        # https://man.sr.ht/git.sr.ht/graphql.md
        request = Request(
            url="https://git.sr.ht/query",
            method="POST",
            headers={
                "authorization": f"bearer {self.token}",
                "content-type": "application/json",
            },
            data=json.dumps(
                {
                    "query": "mutation updateRepository($id: Int!, $input: RepoInput!) { updateRepository(id: $id, input: $input) { id } }",
                    "variables": {
                        "id": id,
                        "input": data,
                    },
                }
            ).encode(),
        )
        response = json.load(opener.open(request))
        if "errors" in response:
            raise Exception(response)


def get_repos(base_dir: Path) -> list[Repo]:
    # https://git.caspervk.net/api/swagger
    response = opener.open(
        "https://git.caspervk.net/api/v1/users/caspervk/repos?limit=1000"
    )
    return [
        Repo(
            base_dir=base_dir,
            clone_url=r["clone_url"],
            default_branch=r["default_branch"],
            description=r["description"],
            html_url=r["html_url"],
            name=r["name"],
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )
        for r in json.load(response)
    ]


def main() -> None:
    codeberg = Codeberg("caspervk", config.CODEBERG_TOKEN)
    github = Github("caspervk", config.GITHUB_TOKEN)
    gitlab = Gitlab("casperxx", config.GITLAB_TOKEN)
    sourcehut = Sourcehut("caspervk", config.SOURCEHUT_TOKEN)

    # Read last run timestamp from state directory
    last_run_file = config.STATE_DIRECTORY.joinpath("last-run")
    try:
        last_run = datetime.fromisoformat(last_run_file.read_text())
    except FileNotFoundError:
        last_run = datetime.min.replace(tzinfo=UTC)
    print("last run:", last_run)

    # Save the time before we start syncing, so we don't miss changes made
    # *while* running.
    now = datetime.now(UTC)
    with NamedTemporaryFile() as ssh_key, TemporaryDirectory() as repo_base_dir:
        ssh_key = Path(ssh_key.name)
        ssh_key.write_text(config.SSH_KEY)
        os.environ["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key}"
        for repo in get_repos(base_dir=Path(repo_base_dir)):
            if repo.updated_at <= last_run:
                print("sync: skipping", repo.name)
                continue
            print("sync: synchronising", repo.name)
            repo.clone()
            codeberg.sync(repo)
            github.sync(repo)
            gitlab.sync(repo)
            sourcehut.sync(repo)

    last_run_file.write_text(now.isoformat())

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

    archived: bool
    clone_url: str
    default_branch: str
    description: str
    html_url: str
    name: str
    updated_at: datetime

    @property
    def path(self) -> Path:
        return self.base_dir.joinpath(self.name)

    def is_remote_up_to_date(self, remote: str) -> bool:
        print("git: is remote up to date?", remote)
        refs_origin = subprocess.run(
            ["git", "ls-remote", self.clone_url],
            check=True,
            capture_output=True,
        )
        refs_remote = subprocess.run(
            ["git", "ls-remote", remote],
            check=True,
            capture_output=True,
        )
        return refs_origin.stdout == refs_remote.stdout

    def clone_or_update(self) -> None:
        if not self.path.exists():
            print("git: clone", self.name)
            subprocess.run(
                ["git", "clone", "--mirror", self.clone_url, self.path],
                check=True,
            )
        else:
            print("git: update", self.name)
            subprocess.run(
                ["git", "remote", "update", "--prune"],
                cwd=self.path,
                check=True,
            )

    def push(self, remote: str) -> None:
        print("git: push", self.name, remote)
        self.clone_or_update()
        subprocess.run(
            ["git", "push", "--mirror", remote],
            cwd=self.path,
            check=True,
        )


class Codeberg:
    def __init__(self, token: str) -> None:
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("codeberg: sync", repo.name)
        remote = f"git@codeberg.org:caspervk/{repo.name}.git"
        self.create(repo.name)
        if not repo.is_remote_up_to_date(remote):
            self.update(name=repo.name, data={"archived": False})
            repo.push(remote)
        self.update(
            name=repo.name,
            data={
                "archived": repo.archived,
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
            url=f"https://codeberg.org/api/v1/repos/caspervk/{name}",
            method="PATCH",
            headers={
                "authorization": f"token {self.token}",
                "content-type": "application/json",
            },
            data=json.dumps(data).encode(),
        )
        opener.open(request)


class Github:
    def __init__(self, token: str) -> None:
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("github: sync", repo.name)
        remote = f"git@github.com:caspervk/{repo.name}.git"
        self.create(repo.name)
        if not repo.is_remote_up_to_date(remote):
            self.update(name=repo.name, data={"archived": False})
            repo.push(remote)
        # GitHub's API can only update if the repo is unarchived. Unarchiving
        # the repo updates the "This repository was archived by the owner on
        # Jan 28, 2026." date, so we only unarchive and update if necessary.
        current = self.get(repo.name)
        if (
            current["archived"] != repo.archived
            or current["default_branch"] != repo.default_branch
            or current["description"] != repo.description
            or current["homepage"] != repo.html_url
        ):
            self.update(name=repo.name, data={"archived": False})
            self.update(
                name=repo.name,
                data={
                    "archived": repo.archived,
                    "default_branch": repo.default_branch,
                    "description": repo.description,
                    "homepage": repo.html_url,
                },
            )

    def get(self, name: str) -> dict:
        print("github: get", name)
        # https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#get-a-repository
        request = Request(
            url=f"https://api.github.com/repos/caspervk/{name}",
            method="GET",
            headers={
                "x-github-api-version": "2022-11-28",
            },
        )
        return json.load(opener.open(request))

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
            url=f"https://api.github.com/repos/caspervk/{name}",
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
    def __init__(self, token: str) -> None:
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("gitlab: sync", repo.name)
        remote = f"git@gitlab.com:casperxx/{repo.name}.git"
        self.create(repo.name)
        if not repo.is_remote_up_to_date(remote):
            self.unarchive(repo.name)
            repo.push(remote)
        current = self.update(
            name=repo.name,
            data={
                "default_branch": repo.default_branch,
                "description": repo.description + "\n\n" + repo.html_url,
            },
        )
        # Gitlab says archive and unarchive is idempotent, but actually you're
        # not allowed to archive a repo that is already archived.
        if current["archived"] != repo.archived:
            if repo.archived:
                self.archive(repo.name)
            else:
                self.unarchive(repo.name)

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
            data=json.dumps({"path": name}).encode(),
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
            url=f"https://gitlab.com/api/v4/projects/casperxx%2F{name}",
            method="PUT",
            headers={
                "content-type": "application/json",
                "private-token": self.token,
            },
            data=json.dumps(data).encode(),
        )
        return json.load(opener.open(request))

    def archive(self, name: str) -> None:
        print("gitlab: archive", name)
        # https://docs.gitlab.com/api/projects/#archive-a-project
        request = Request(
            url=f"https://gitlab.com/api/v4/projects/casperxx%2F{name}/archive",
            method="POST",
            headers={
                "private-token": self.token,
            },
        )
        opener.open(request)

    def unarchive(self, name: str) -> None:
        print("gitlab: unarchive", name)
        # https://docs.gitlab.com/api/projects/#unarchive-a-project
        request = Request(
            url=f"https://gitlab.com/api/v4/projects/casperxx%2F{name}/unarchive",
            method="POST",
            headers={
                "private-token": self.token,
            },
        )
        opener.open(request)


class Sourcehut:
    def __init__(self, token: str) -> None:
        self.token = token

    def sync(self, repo: Repo) -> None:
        print("sourcehut: sync", repo.name)
        remote = f"git@git.sr.ht:~caspervk/{repo.name}"
        self.create(repo.name)
        if not repo.is_remote_up_to_date(remote):
            # Can't archive repos, so no need to unarchive before pushing
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
            archived=r["archived"],
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
    codeberg = Codeberg(config.CODEBERG_TOKEN)
    github = Github(config.GITHUB_TOKEN)
    gitlab = Gitlab(config.GITLAB_TOKEN)
    sourcehut = Sourcehut(config.SOURCEHUT_TOKEN)

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
            codeberg.sync(repo)
            github.sync(repo)
            gitlab.sync(repo)
            sourcehut.sync(repo)

    last_run_file.write_text(now.isoformat())

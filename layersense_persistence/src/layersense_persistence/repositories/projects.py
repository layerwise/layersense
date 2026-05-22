from sqlalchemy import select
from sqlalchemy.orm import Session

from layersense_persistence.models import Project, utc_now_iso
from layersense_persistence.repositories._common import new_id, slugify


class ProjectsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        name: str,
        slug: str | None = None,
        default_render_config_json: str = "{}",
    ) -> Project:
        project = Project(
            id=new_id(),
            name=name,
            slug=self._unique_slug(slug or slugify(name)),
            default_render_config_json=default_render_config_json,
        )
        self.session.add(project)
        self.session.flush()
        return project

    def get(self, project_id: str) -> Project | None:
        return self.session.get(Project, project_id)

    def get_by_slug(self, slug: str) -> Project | None:
        return self.session.scalar(select(Project).where(Project.slug == slug))

    def list(self) -> list[Project]:
        return list(
            self.session.scalars(select(Project).order_by(Project.created_at, Project.name))
        )

    def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        default_render_config_json: str | None = None,
    ) -> Project:
        project = self._require(project_id)
        if name is not None:
            project.name = name
        if default_render_config_json is not None:
            project.default_render_config_json = default_render_config_json
        project.updated_at = utc_now_iso()
        self.session.flush()
        return project

    def delete(self, project_id: str) -> None:
        project = self._require(project_id)
        self.session.delete(project)
        self.session.flush()

    def _require(self, project_id: str) -> Project:
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        return project

    def _unique_slug(self, base_slug: str) -> str:
        slug = base_slug
        suffix = 2
        while self.get_by_slug(slug) is not None:
            suffix_text = f"-{suffix}"
            slug = f"{base_slug[: 80 - len(suffix_text)]}{suffix_text}"
            suffix += 1
        return slug

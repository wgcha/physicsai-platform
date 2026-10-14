import { Link } from "react-router-dom";
import { useApp, roleIn } from "../app/AppContext";
import { ROLE_LABEL } from "../lib/format";
import { TopBar } from "../shell/TopBar";
import { Cell, Grid } from "../design/Grid";

export function ProjectList() {
  const { me, projects } = useApp();
  return (
    <div className="page">
      <TopBar crumbs={[]} />
      <main className="page-main">
        <div className="page-title-row">
          <h1 className="page-title T">프로젝트 선택</h1>
          <p className="muted">대시보드 프로젝트입니다. Study는 프로젝트 안에 만듭니다.</p>
        </div>
        {projects.length === 0 ? (
          <div className="empty">표시할 프로젝트가 없습니다</div>
        ) : (
          <Grid as="ul" className="tile-list">
            {projects.map((p) => {
              const r = roleIn(me, p.id);
              return (
                <Cell as="li" span={3} key={p.id}>
                  <Link className="tile" to={`/p/${p.id}`}>
                    <span className="tile-title T">{p.name}</span>
                    <span className="muted small">{p.product_name ?? ""}</span>
                    <span className={`role-chip ${r ?? "general"}`}>{r ? ROLE_LABEL[r] : "비멤버(조회)"}</span>
                  </Link>
                </Cell>
              );
            })}
          </Grid>
        )}
      </main>
    </div>
  );
}

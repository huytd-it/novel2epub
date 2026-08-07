import { Page } from "@/app/Shell";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { IconExternal } from "@/components/icons";
import { useLocation } from "react-router";
import { legacyUrl } from "@/lib/api";

/** Trang chưa port: chỉ đường sang bản Jinja2 tương ứng thay vì để trống. */
export function PlaceholderPage({ title }: { title: string }) {
  const { pathname } = useLocation();
  const legacy = legacyUrl(pathname === "/" ? "/" : pathname);

  return (
    <Page title={title}>
      <Panel>
        <EmptyState
          title="Trang này chưa chuyển sang giao diện mới"
          hint="Bản cũ vẫn hoạt động đầy đủ trong lúc chờ port. Mở nó trong tab khác để làm tiếp."
          action={
            <Button
              variant="neutral"
              icon={<IconExternal />}
              onClick={() => window.open(legacy, "_blank", "noopener")}
            >
              Mở bản cũ
            </Button>
          }
        />
      </Panel>
    </Page>
  );
}

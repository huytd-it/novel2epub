import { Page } from "@/app/Shell";
import { Panel, EmptyState } from "@/components/ui/Panel";

/** Trang chưa port: hiển thị trạng thái trống thay vì để trắng. */
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <Page title={title}>
      <Panel>
        <EmptyState title="Trang này chưa chuyển sang giao diện mới" />
      </Panel>
    </Page>
  );
}

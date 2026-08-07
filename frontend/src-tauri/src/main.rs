// Không mở console phụ khi chạy bản release trên Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    novel2epub_desktop_lib::run()
}

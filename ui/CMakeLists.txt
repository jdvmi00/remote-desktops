cmake_minimum_required(VERSION 3.21)
project(RemoteDesktopsManager VERSION 0.1.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 6.4 REQUIRED COMPONENTS Quick QuickControls2 Network Test)
set(QML_FILES
    qml/Main.qml qml/KeyboardDialog.qml qml/SetupDialog.qml qml/ActionButton.qml qml/IconButton.qml qml/Icon.qml qml/Tip.qml
    qml/Bar.qml qml/Field.qml qml/Check.qml qml/Spin.qml qml/Select.qml qml/Combo.qml qml/StatusDot.qml
    qml/Sheet.qml qml/Confirm.qml qml/Toast.qml qml/ComputerGlyph.qml)
set(ICON_FILES
    qml/icons/alert.svg qml/icons/arrow-left.svg qml/icons/check.svg qml/icons/chevron-down.svg qml/icons/chevron-right.svg qml/icons/close.svg
    qml/icons/copy.svg qml/icons/external.svg qml/icons/grid.svg qml/icons/help.svg qml/icons/info.svg
    qml/icons/laptop.svg qml/icons/minus.svg qml/icons/monitor.svg qml/icons/pencil.svg qml/icons/play.svg
    qml/icons/plus.svg qml/icons/power.svg qml/icons/refresh.svg qml/icons/sliders.svg qml/icons/trash.svg)
qt_add_executable(remote-desktops-manager main.cpp Manager.cpp Manager.h Theme.cpp Theme.h)
qt_add_resources(remote-desktops-manager qml PREFIX "/" FILES ${QML_FILES} ${ICON_FILES})
target_link_libraries(remote-desktops-manager PRIVATE Qt6::Quick Qt6::QuickControls2 Qt6::Network)
target_compile_options(remote-desktops-manager PRIVATE -Wall -Wextra -Wpedantic)
enable_testing()
qt_add_executable(manager-tests tests/manager.cpp Manager.cpp Manager.h Theme.cpp Theme.h)
target_link_libraries(manager-tests PRIVATE Qt6::Test Qt6::Network Qt6::Quick Qt6::QuickControls2)
qt_add_resources(manager-tests qmlTests PREFIX "/" FILES ${QML_FILES} ${ICON_FILES})
set(TEST_ENVIRONMENT "QT_QPA_PLATFORM=offscreen;QT_QUICK_BACKEND=software")
add_test(NAME manager COMMAND manager-tests)
set_tests_properties(manager PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")
add_test(NAME qml-smoke COMMAND remote-desktops-manager --demo --smoke-test)
set_tests_properties(qml-smoke PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")

foreach(state idle connecting preflight running attention restore-pending empty unavailable many unconfigured)
    add_test(NAME qml-${state} COMMAND remote-desktops-manager --demo --state ${state} --smoke-test)
    set_tests_properties(qml-${state} PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")
endforeach()
add_test(NAME qml-compact COMMAND remote-desktops-manager --demo --state many --compact --smoke-test)
set_tests_properties(qml-compact PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")
add_test(NAME qml-light COMMAND remote-desktops-manager --demo --state restore-pending --theme-file ${CMAKE_CURRENT_SOURCE_DIR}/tests/light.toml --smoke-test)
set_tests_properties(qml-light PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")
add_test(NAME qml-setup COMMAND remote-desktops-manager --demo --setup-preview computer --compact --smoke-test)
set_tests_properties(qml-setup PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")

foreach(page pair preferences recovery windows matching advanced check)
    add_test(NAME qml-setup-${page} COMMAND remote-desktops-manager --demo --setup-preview ${page} --compact --smoke-test)
    set_tests_properties(qml-setup-${page} PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")
endforeach()

foreach(surface help details remove notice error preferences keyboard)
    add_test(NAME qml-dialog-${surface} COMMAND remote-desktops-manager --demo --state idle --dialog ${surface} --smoke-test)
    set_tests_properties(qml-dialog-${surface} PROPERTIES ENVIRONMENT "${TEST_ENVIRONMENT}")
endforeach()

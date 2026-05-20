clean:
	rm -rf build

deploy_apps:
	echo "deploy_apps is not implemented."


lint: lint_helm lint_python

lint_helm:
	./scripts/lint_helm.sh

lint_python:
	./scripts/lint_python.sh


package: package_docker package_helm

package_docker:
	./scripts/package_docker.sh

package_helm:
	./scripts/package_helm.sh


publish: publish_docker publish_helm

publish_docker:
	./scripts/publish_docker.sh

publish_helm:
	echo "publish_helm is not implemented."


test: test_python test_node

test_python:
	./scripts/test_python.sh

test_node:
	./scripts/test_node.sh


version:
	./scripts/update_version.py
	GIT_PAGER=cat git diff helm/Chart.yaml

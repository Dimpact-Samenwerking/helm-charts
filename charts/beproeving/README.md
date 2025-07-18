# Beproeving helm chart

### https://dimpact.atlassian.net/wiki/spaces/PCP/pages/468287492/Helm+chart+voor+beproeving

# Introduction
Many new components and functionalities are being added to podiumd. Currently, all newly delivered components are integrated directly into the podiumd Helm chart.

Normally, new components are first tested in a municipality’s beproeving (trial/testing) environment. However, these new components are now always included by default and immediately enabled, even though they are not yet fully finished.

# What are we going to do?
We will stop delivering new components directly in the podiumd Helm chart. Instead, we will first test them ourselves using the beproeving Helm chart, so they can be tried out in a few environments. These include the development environments of the development partners (P:CT) and the partner test environment (P:PT).

If a municipality wants to beproef a component that is not yet included in the podiumd Helm chart, we can configure the same Azure DevOps pipeline to deploy to a municipal beproeving environment.

This approach allows components to be tested while the required configuration and other prerequisites are still being finalized.
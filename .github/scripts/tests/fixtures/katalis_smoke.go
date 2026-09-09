// Run the installed Katalis pair against a disposable, real Kubernetes control plane.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
	clientcmdapi "k8s.io/client-go/tools/clientcmd/api"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
)

type process struct {
	cmd  *exec.Cmd
	done chan struct{}
	err  error
}

func (p *process) alive() error {
	select {
	case <-p.done:
		return fmt.Errorf("%s exited before the checks completed: %v", p.cmd.Path, p.err)
	default:
		return nil
	}
}

func run() (runErr error) {
	operator := flag.String("operator", "", "Installed operator binary")
	api := flag.String("api", "", "Installed API binary")
	assets := flag.String("assets", "", "Verified native envtest assets")
	crds := flag.String("crds", "", "CRDs from the pinned operator source")
	state := flag.String("state", "", "Private scratch directory")
	flag.Parse()
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	ctx, deadline := context.WithTimeout(ctx, 180*time.Second)
	defer deadline()
	control := &envtest.Environment{
		BinaryAssetsDirectory: *assets, CRDDirectoryPaths: []string{*crds},
		ErrorIfCRDPathMissing: true, ControlPlaneStartTimeout: 45 * time.Second,
		ControlPlaneStopTimeout:  15 * time.Second,
		AttachControlPlaneOutput: true,
	}
	control.ControlPlane.GetAPIServer().Configure().Set("advertise-address", "127.0.0.1")
	defer func() {
		if err := control.Stop(); err != nil && runErr == nil {
			runErr = fmt.Errorf("stop isolated Kubernetes: %w", err)
		}
	}()
	cfg, err := control.Start()
	if err != nil {
		return fmt.Errorf("start isolated Kubernetes: %w", err)
	}
	cfg.Timeout = 5 * time.Second
	kubeconfig := filepath.Join(*state, "kubeconfig")
	config := clientcmdapi.Config{
		Clusters:       map[string]*clientcmdapi.Cluster{"smoke": {Server: cfg.Host, CertificateAuthorityData: cfg.CAData}},
		AuthInfos:      map[string]*clientcmdapi.AuthInfo{"smoke": {ClientCertificateData: cfg.CertData, ClientKeyData: cfg.KeyData}},
		Contexts:       map[string]*clientcmdapi.Context{"smoke": {Cluster: "smoke", AuthInfo: "smoke"}},
		CurrentContext: "smoke",
	}
	if err := clientcmd.WriteToFile(config, kubeconfig); err != nil {
		return err
	}
	kube, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		return err
	}
	dyn, err := dynamic.NewForConfig(cfg)
	if err != nil {
		return err
	}
	const ns = "katalis-smoke"
	if _, err := kube.CoreV1().Namespaces().Create(ctx, &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: ns}}, metav1.CreateOptions{}); err != nil {
		return err
	}
	var processes []*process
	defer func() {
		for _, p := range processes {
			_ = p.cmd.Process.Signal(syscall.SIGTERM)
		}
		for _, p := range processes {
			select {
			case <-p.done:
			case <-time.After(5 * time.Second):
				_ = p.cmd.Process.Kill()
				<-p.done
			}
		}
	}()
	start := func(binary, name string, env []string, args ...string) error {
		log, err := os.Create(filepath.Join(*state, name+".log"))
		if err != nil {
			return err
		}
		cmd := exec.CommandContext(ctx, binary, args...)
		// The workflow supplies an isolated container environment, without host secrets.
		cmd.Env = append(os.Environ(), "KUBECONFIG="+kubeconfig, "USER=katalis-smoke")
		cmd.Env = append(cmd.Env, env...)
		cmd.Stdout, cmd.Stderr = log, log
		if err := cmd.Start(); err != nil {
			log.Close()
			return err
		}
		p := &process{cmd: cmd, done: make(chan struct{})}
		processes = append(processes, p)
		go func() { p.err = cmd.Wait(); log.Close(); close(p.done) }()
		return nil
	}
	alive := func() error {
		for _, p := range processes {
			if err := p.alive(); err != nil {
				return err
			}
		}
		return ctx.Err()
	}
	poll := func(label string, check func() (bool, error)) error {
		end := time.Now().Add(45 * time.Second)
		for time.Now().Before(end) {
			if err := alive(); err != nil {
				return err
			}
			ok, err := check()
			if err != nil {
				return fmt.Errorf("%s: %w", label, err)
			}
			if ok {
				fmt.Println(label)
				return nil
			}
			time.Sleep(250 * time.Millisecond)
		}
		return fmt.Errorf("timed out: %s", label)
	}
	if err := start(*operator, "operator", []string{"NAMESPACE=" + ns}, "--health-probe-bind-address=127.0.0.1:0", "--metrics-bind-address=0"); err != nil {
		return err
	}
	const federationID = "3acde22c-d245-480d-b01e-24e38e01806d"
	const zoneID = "2a8fffaf-50de-4f93-8c6f-05f1c84b5a5f"
	federations := dyn.Resource(schema.GroupVersionResource{Group: "opg.ewbi.nby.one", Version: "v1beta1", Resource: "federations"}).Namespace(ns)
	federation := &unstructured.Unstructured{Object: map[string]interface{}{
		"apiVersion": "opg.ewbi.nby.one/v1beta1", "kind": "Federation",
		"metadata": map[string]interface{}{"name": "native-federation", "namespace": ns, "labels": map[string]interface{}{
			"opg.ewbi.nby.one/federation-relation": "host", "opg.ewbi.nby.one/id": federationID,
			"opg.ewbi.nby.one/federation-context-id": federationID,
		}},
		"spec": map[string]interface{}{
			"originOP": map[string]interface{}{"countryCode": "US", "fixedNetworkCodes": []interface{}{"native-smoke"},
				"mobileNetworkCodes": map[string]interface{}{"mcc": "001", "mncs": []interface{}{"001"}}},
			"offeredAvailabilityZones": []interface{}{map[string]interface{}{"zoneId": zoneID, "geolocation": "41.8781,-87.6298", "geographyDetails": "native-arm64"}},
		},
	}}
	if _, err := federations.Create(ctx, federation, metav1.CreateOptions{}); err != nil {
		return err
	}
	if err := poll("operator reconciled Federation to Ready with its finalizer", func() (bool, error) {
		obj, err := federations.Get(ctx, "native-federation", metav1.GetOptions{})
		if err != nil {
			return false, err
		}
		phase, _, _ := unstructured.NestedString(obj.Object, "status", "phase")
		for _, f := range obj.GetFinalizers() {
			if f == "federation.opg.ewbi.finalizer.nby.one" && phase == "Ready" {
				return true, nil
			}
		}
		return false, nil
	}); err != nil {
		return err
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	addr := listener.Addr().String()
	listener.Close()
	if err := start(*api, "api", []string{"CONTROLLER_NAMESPACE=" + ns, "CAMARA_HOST_AGENT_ADDR=" + addr}); err != nil {
		return err
	}
	client := &http.Client{Timeout: 3 * time.Second}
	request := func(method, path, body string) (int, []byte, error) {
		req, err := http.NewRequestWithContext(ctx, method, "http://"+addr+path, bytes.NewBufferString(body))
		if err != nil {
			return 0, nil, err
		}
		req.Header.Set("X-Client-ID", federationID)
		req.Header.Set("Content-Type", "application/json")
		res, err := client.Do(req)
		if err != nil {
			return 0, nil, err
		}
		defer res.Body.Close()
		data, err := io.ReadAll(io.LimitReader(res.Body, 1<<20))
		return res.StatusCode, data, err
	}
	path := "/" + federationID + "/partner"
	if err := poll("API returned persisted federation network codes and offered zone", func() (bool, error) {
		status, body, err := request("GET", path, "")
		if err != nil {
			return false, nil
		}
		if status != 200 {
			return false, fmt.Errorf("HTTP %d: %s", status, body)
		}
		var value struct {
			Networks struct {
				MCC string `json:"mcc"`
			} `json:"allowedMobileNetworkIds"`
			Zones []struct {
				ID        string `json:"zoneId"`
				Geography string `json:"geographyDetails"`
			} `json:"offeredAvailabilityZones"`
		}
		if err := json.Unmarshal(body, &value); err != nil {
			return false, err
		}
		if value.Networks.MCC != "001" || len(value.Zones) != 1 || value.Zones[0].ID != zoneID || value.Zones[0].Geography != "native-arm64" {
			return false, fmt.Errorf("wrong federation response: %s", body)
		}
		return true, nil
	}); err != nil {
		return err
	}
	status, body, err := request("POST", "/"+federationID+"/zones", `{"acceptedAvailabilityZones":["`+zoneID+`"],"availZoneNotifLink":"http://`+addr+`/callback"}`)
	if err != nil || status != 200 {
		return fmt.Errorf("subscribe zone: HTTP %d %s: %v", status, body, err)
	}
	if err := poll("API zone subscription persisted in Kubernetes", func() (bool, error) {
		obj, err := federations.Get(ctx, "native-federation", metav1.GetOptions{})
		if err != nil {
			return false, err
		}
		zones, _, err := unstructured.NestedStringSlice(obj.Object, "spec", "acceptedAvailabilityZones")
		return len(zones) == 1 && zones[0] == zoneID, err
	}); err != nil {
		return err
	}
	status, body, err = request("DELETE", path, "")
	if err != nil || status != 200 {
		return fmt.Errorf("delete federation: HTTP %d %s: %v", status, body, err)
	}
	if err := poll("API deletion completed through operator finalizer reconciliation", func() (bool, error) {
		_, err := federations.Get(ctx, "native-federation", metav1.GetOptions{})
		if apierrors.IsNotFound(err) {
			return true, nil
		}
		return false, err
	}); err != nil {
		return err
	}
	time.Sleep(500 * time.Millisecond)
	if err := alive(); err != nil {
		return err
	}
	fmt.Println("both Katalis processes survived all functional checks")
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

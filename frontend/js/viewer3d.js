/**
 * frontend/js/viewer3d.js
 * Three.js 3D spatial plot visualizer.
 * Projects WGS84 GeoJSON polygons to local metric coordinates.
 * Extrudes 3D mesh representations with real-time state coloring:
 * - Green = Clear with active Ask
 * - Blue = Clear not listed
 * - Amber = Pending
 * - Red = Disputed
 * - White outline = Owned by current logged-in user
 */

export class PlotViewer3D {
  constructor(canvasContainerId, onPlotSelectCallback) {
    this.container = document.getElementById(canvasContainerId);
    this.onPlotSelect = onPlotSelectCallback;
    this.plotsData = [];
    this.plotMeshes = new Map();
    this.centroid = { lon: 77.5946, lat: 12.9716 }; // Bengaluru default
    this.currentUserOwnerId = null;

    this.initScene();
    this.initInteraction();
    this.animate();
  }

  setCurrentUser(ownerId) {
    this.currentUserOwnerId = ownerId;
    this.updateMeshStyles();
  }

  initScene() {
    // 1. WebGL2 Check
    const canvas = document.createElement('canvas');
    const gl2 = canvas.getContext('webgl2');
    if (!gl2) {
      this.container.innerHTML = `
        <div style="padding: 40px; color: #ef4444; text-align: center;">
          <h2>WebGL 2.0 Not Supported</h2>
          <p>Please use a modern browser with hardware acceleration enabled to view the 3D land parcels.</p>
        </div>`;
      return;
    }

    // 2. Three.js Setup
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x080c14);
    this.scene.fog = new THREE.FogExp2(0x080c14, 0.001);

    const width = this.container.clientWidth;
    const height = this.container.clientHeight;

    this.camera = new THREE.PerspectiveCamera(45, width / height, 1, 2000);
    this.camera.position.set(0, 150, 200);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.shadowMap.enabled = true;
    this.container.appendChild(this.renderer.domElement);

    // 3. OrbitControls
    if (typeof THREE.OrbitControls !== 'undefined') {
      this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.05;
      this.controls.maxPolarAngle = Math.PI / 2 - 0.05; // Don't go below ground
    }

    // 4. Lights & Grid
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    this.scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(100, 200, 100);
    dirLight.castShadow = true;
    this.scene.add(dirLight);

    const grid = new THREE.GridHelper(500, 50, 0x1e293b, 0x0f172a);
    grid.position.y = -0.5;
    this.scene.add(grid);

    // Responsive resize
    window.addEventListener('resize', () => this.onWindowResize());
  }

  onWindowResize() {
    if (!this.renderer || !this.container) return;
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  // Equirectangular projection from lon/lat to local meters
  projectToMeters(lon, lat) {
    const latRad = (this.centroid.lat * Math.PI) / 180;
    const x = (lon - this.centroid.lon) * 111320 * Math.cos(latRad);
    const z = -(lat - this.centroid.lat) * 110540;
    return { x, z };
  }

  loadPlots(plots) {
    this.plotsData = plots;

    // Clear existing plot meshes
    for (const [_, group] of this.plotMeshes) {
      this.scene.remove(group);
    }
    this.plotMeshes.clear();

    if (!plots || plots.length === 0) return;

    // Calculate global centroid from first polygon
    try {
      const firstCoords = plots[0].geojson.coordinates[0];
      this.centroid = { lon: firstCoords[0][0], lat: firstCoords[0][1] };
    } catch (e) {
      this.centroid = { lon: 77.5946, lat: 12.9716 };
    }

    plots.forEach(plot => this.createPlotMesh(plot));
  }

  createPlotMesh(plot) {
    if (!plot.geojson || !plot.geojson.coordinates) return;

    const coords = plot.geojson.coordinates[0];
    const shape = new THREE.Shape();

    coords.forEach((coord, index) => {
      const pt = this.projectToMeters(coord[0], coord[1]);
      if (index === 0) {
        shape.moveTo(pt.x, pt.z);
      } else {
        shape.lineTo(pt.x, pt.z);
      }
    });

    const extrudeSettings = {
      depth: 6,
      bevelEnabled: true,
      bevelSegments: 2,
      steps: 1,
      bevelSize: 0.5,
      bevelThickness: 0.5
    };

    const geometry = new THREE.ExtrudeGeometry(shape, extrudeSettings);
    geometry.rotateX(Math.PI / 2); // Orient horizontally

    const color = this.getPlotColor(plot);
    const material = new THREE.MeshStandardMaterial({
      color: color,
      roughness: 0.4,
      metalness: 0.1,
      transparent: true,
      opacity: 0.88
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    // Edge wireframe outline
    const edges = new THREE.EdgesGeometry(geometry);
    const isOwner = this.currentUserOwnerId && plot.owner_id === this.currentUserOwnerId;
    const lineMaterial = new THREE.LineBasicMaterial({
      color: isOwner ? 0xffffff : 0x000000,
      linewidth: isOwner ? 3 : 1
    });
    const edgeLines = new THREE.LineSegments(edges, lineMaterial);

    const group = new THREE.Group();
    group.add(mesh);
    group.add(edgeLines);
    group.userData = { plot: plot, mesh: mesh, edgeLines: edgeLines };

    this.scene.add(group);
    this.plotMeshes.set(plot.plot_id, group);
  }

  getPlotColor(plot) {
    // Real-time state color rule
    if (plot.status === "Disputed") return 0xef4444; // Red
    if (plot.status === "Pending") return 0xf59e0b;  // Amber
    if (plot.status === "Clear") {
      if (plot.active_ask !== null && plot.active_ask !== undefined) {
        return 0x22c55e; // Green (Clear with active Ask)
      }
      return 0x3b82f6;   // Blue (Clear, not listed)
    }
    return 0x64748b;
  }

  updateMeshStyles() {
    this.plotMeshes.forEach((group) => {
      const plot = group.userData.plot;
      const mesh = group.userData.mesh;
      const lines = group.userData.edgeLines;

      mesh.material.color.setHex(this.getPlotColor(plot));

      const isOwner = this.currentUserOwnerId && plot.owner_id === this.currentUserOwnerId;
      lines.material.color.setHex(isOwner ? 0xffffff : 0x000000);
    });
  }

  initInteraction() {
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2();
    this.hoveredMesh = null;
    this.hoveredMeshOrigColor = null;
    this.tooltipElement = document.getElementById('plot-tooltip');

    // Mouse move: Raycast for hovering effects, cursor change, and floating tooltip
    this.container.addEventListener('mousemove', (event) => {
      const rect = this.container.getBoundingClientRect();
      this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      this.raycaster.setFromCamera(this.mouse, this.camera);
      const intersects = this.raycaster.intersectObjects(this.scene.children, true);

      let foundGroup = null;
      if (intersects.length > 0) {
        let target = intersects[0].object;
        while (target.parent && target.parent !== this.scene && !target.userData.plot) {
          target = target.parent;
        }
        if (target.userData && target.userData.plot) {
          foundGroup = target;
        }
      }

      if (foundGroup) {
        this.container.style.cursor = 'pointer';
        const plot = foundGroup.userData.plot;
        const mesh = foundGroup.userData.mesh;

        // Highlight mesh on hover
        if (this.hoveredMesh !== mesh) {
          if (this.hoveredMesh && this.hoveredMeshOrigColor !== null) {
            this.hoveredMesh.material.color.setHex(this.hoveredMeshOrigColor);
          }
          this.hoveredMesh = mesh;
          this.hoveredMeshOrigColor = this.getPlotColor(plot);
          // Brighten mesh color slightly on hover
          const hoverColor = new THREE.Color(this.hoveredMeshOrigColor).offsetHSL(0, 0.05, 0.15);
          mesh.material.color.copy(hoverColor);
        }

        // Show floating tooltip
        if (this.tooltipElement) {
          const isAvailable = plot.status === 'Clear' && plot.active_ask !== null && plot.active_ask !== undefined;
          const statusColor = plot.status === 'Disputed' ? '#ef4444' : (plot.status === 'Pending' ? '#f59e0b' : (isAvailable ? '#22c55e' : '#3b82f6'));
          const availabilityBadge = isAvailable
            ? '<span class="tooltip-badge" style="background: rgba(34, 197, 94, 0.2); color: #4ade80;">Available for Sale</span>'
            : (plot.status === 'Clear' 
                ? '<span class="tooltip-badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa;">Not Listed</span>'
                : `<span class="tooltip-badge" style="background: rgba(239, 68, 68, 0.2); color: #f87171;">${plot.status}</span>`);

          const priceHtml = plot.active_ask
            ? `₹${Number(plot.active_ask).toLocaleString()}`
            : (plot.best_bid ? `Best Bid: ₹${Number(plot.best_bid).toLocaleString()}` : '<span style="color:#94a3b8">No Active Ask</span>');

          this.tooltipElement.innerHTML = `
            <div class="tooltip-header">
              <span>${plot.plot_id}</span>
              ${availabilityBadge}
            </div>
            <div class="tooltip-row">
              <span>Address:</span>
              <strong style="max-width: 140px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${plot.street_address || 'Bengaluru Parcel'}</strong>
            </div>
            <div class="tooltip-row">
              <span>Area:</span>
              <span>${plot.area_sqft ? Math.round(plot.area_sqft).toLocaleString() + ' sq ft' : '--'}</span>
            </div>
            <div class="tooltip-row" style="margin-top: 6px; padding-top: 4px; border-top: 1px dashed rgba(255,255,255,0.1);">
              <span style="font-weight: 600;">Price:</span>
              <strong style="color: ${isAvailable ? '#4ade80' : '#f8fafc'}; font-size: 0.9rem;">${priceHtml}</strong>
            </div>
          `;

          // Position tooltip relative to container, offset slightly from mouse
          const posX = event.clientX - rect.left + 15;
          const posY = event.clientY - rect.top + 15;
          this.tooltipElement.style.left = `${posX}px`;
          this.tooltipElement.style.top = `${posY}px`;
          this.tooltipElement.classList.remove('hidden');
        }
      } else {
        this.container.style.cursor = 'default';
        if (this.hoveredMesh && this.hoveredMeshOrigColor !== null) {
          this.hoveredMesh.material.color.setHex(this.hoveredMeshOrigColor);
          this.hoveredMesh = null;
          this.hoveredMeshOrigColor = null;
        }
        if (this.tooltipElement) {
          this.tooltipElement.classList.add('hidden');
        }
      }
    });

    this.container.addEventListener('mouseleave', () => {
      if (this.hoveredMesh && this.hoveredMeshOrigColor !== null) {
        this.hoveredMesh.material.color.setHex(this.hoveredMeshOrigColor);
        this.hoveredMesh = null;
        this.hoveredMeshOrigColor = null;
      }
      if (this.tooltipElement) {
        this.tooltipElement.classList.add('hidden');
      }
    });

    this.container.addEventListener('click', (event) => {
      const rect = this.container.getBoundingClientRect();
      this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      this.raycaster.setFromCamera(this.mouse, this.camera);
      const intersects = this.raycaster.intersectObjects(this.scene.children, true);

      if (intersects.length > 0) {
        let target = intersects[0].object;
        while (target.parent && target.parent !== this.scene && !target.userData.plot) {
          target = target.parent;
        }

        if (target.userData && target.userData.plot) {
          const plot = target.userData.plot;
          if (this.onPlotSelect) {
            this.onPlotSelect(plot);
          }
        }
      }
    });
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    if (this.controls) this.controls.update();
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }
}
